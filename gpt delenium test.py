from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import time
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from openai import OpenAI
from quantsearch import search_qdrant_and_summarize
import os
from dotenv import load_dotenv
# --- Conversation Memory Imports ---
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List
from dataclasses import dataclass
import random


load_dotenv("C:/Users/Rono/Desktop/Ai agent trial/.env")

SAMBA_API_KEY = os.getenv("SAMBA_API_KEY")
SAMBA_CATEGORIZE_API_KEY = os.getenv("SAMBA_CATEGORIZE_API_KEY")

# --- Conversation Memory Classes ---
@dataclass
class Message:
    timestamp: datetime
    sender: str  # "user" or "bot"
    content: str
    message_type: str  # "news", "chat", etc.

class ConversationMemory:
    def __init__(self, db_path: str = "conversation_memory.db", max_context_messages: int = 10):
        self.db_path = db_path
        self.max_context_messages = max_context_messages
        self.current_conversations = defaultdict(list)
        self.init_database()
    def init_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contact_name TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                sender TEXT NOT NULL,
                content TEXT NOT NULL,
                message_type TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS conversation_context (
                contact_name TEXT PRIMARY KEY,
                context_summary TEXT,
                last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        conn.close()
    def add_message(self, contact_name: str, sender: str, content: str, message_type: str = "chat"):
        timestamp = datetime.now()
        message = Message(timestamp, sender, content, message_type)
        self.current_conversations[contact_name].append(message)
        if len(self.current_conversations[contact_name]) > self.max_context_messages * 2:
            self.current_conversations[contact_name] = self.current_conversations[contact_name][-self.max_context_messages:]
        self._save_to_db(contact_name, message)
    def _save_to_db(self, contact_name: str, message: Message):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO conversations (contact_name, timestamp, sender, content, message_type)
            VALUES (?, ?, ?, ?, ?)
        ''', (contact_name, message.timestamp.isoformat(), message.sender, message.content, message.message_type))
        conn.commit()
        conn.close()
    def get_conversation_context(self, contact_name: str, include_system_prompt: bool = True) -> List[Dict]:
        if contact_name not in self.current_conversations:
            self._load_recent_messages(contact_name)
        messages = self.current_conversations[contact_name]
        recent_messages = messages[-self.max_context_messages:] if messages else []
        context = []
        if include_system_prompt:
            context.append({
                "role": "system",
                "content": self._generate_system_prompt(contact_name)
            })
        for msg in recent_messages:
            role = "user" if msg.sender == "user" else "assistant"
            context.append({
                "role": role,
                "content": msg.content
            })
        return context
    def _load_recent_messages(self, contact_name: str):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT timestamp, sender, content, message_type
            FROM conversations
            WHERE contact_name = ?
            ORDER BY timestamp DESC
            LIMIT ?
        ''', (contact_name, self.max_context_messages))
        rows = cursor.fetchall()
        conn.close()
        messages = []
        for row in reversed(rows):
            timestamp = datetime.fromisoformat(row[0])
            messages.append(Message(timestamp, row[1], row[2], row[3]))
        self.current_conversations[contact_name] = messages
    def _generate_system_prompt(self, contact_name: str) -> str:
        context_summary = self._get_conversation_summary(contact_name)
        base_prompt = f"""You are a helpful AI assistant chatting with {contact_name} on WhatsApp.\n\nPrevious conversation context: {context_summary}\n\nGuidelines:\n- Remember previous topics and maintain continuity\n- For capability questions about news, explain your process without searching\n- For actual news requests, provide recent information\n- Keep responses concise and WhatsApp-appropriate\n- Be conversational and natural"""
        return base_prompt
    def _get_conversation_summary(self, contact_name: str) -> str:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT context_summary, last_updated
            FROM conversation_context
            WHERE contact_name = ?
        ''', (contact_name,))
        row = cursor.fetchone()
        conn.close()
        if row and datetime.fromisoformat(row[1]) > datetime.now() - timedelta(hours=24):
            return row[0]
        return self._generate_conversation_summary(contact_name)
    def _generate_conversation_summary(self, contact_name: str) -> str:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT content, sender, message_type
            FROM conversations
            WHERE contact_name = ?
            ORDER BY timestamp DESC
            LIMIT 50
        ''', (contact_name,))
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            return "No previous conversation history."
        topics = []
        news_queries = []
        for content, sender, msg_type in rows:
            if msg_type == "news":
                news_queries.append(content)
            elif len(content) > 20:
                topics.append(content[:100])
        summary = f"Recent conversation with {contact_name}. "
        if news_queries:
            summary += f"They've asked about: {', '.join(news_queries[-3:])}. "
        if topics:
            summary += f"Recent topics discussed: {', '.join(topics[-3:])}."
        self._save_conversation_summary(contact_name, summary)
        return summary
    def _save_conversation_summary(self, contact_name: str, summary: str):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO conversation_context (contact_name, context_summary, last_updated)
            VALUES (?, ?, ?)
        ''', (contact_name, summary, datetime.now().isoformat()))
        conn.commit()
        conn.close()
    def get_conversation_stats(self, contact_name: str) -> Dict:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) as total_messages,
                   COUNT(CASE WHEN sender = 'user' THEN 1 END) as user_messages,
                   COUNT(CASE WHEN sender = 'bot' THEN 1 END) as bot_messages,
                   COUNT(CASE WHEN message_type = 'news' THEN 1 END) as news_queries,
                   MIN(timestamp) as first_message,
                   MAX(timestamp) as last_message
            FROM conversations
            WHERE contact_name = ?
        ''', (contact_name,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return {
                "total_messages": row[0],
                "user_messages": row[1],
                "bot_messages": row[2],
                "news_queries": row[3],
                "first_message": row[4],
                "last_message": row[5]
            }
        return {}
    def clear_old_conversations(self, days_old: int = 30):
        cutoff_date = datetime.now() - timedelta(days=days_old)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            DELETE FROM conversations
            WHERE timestamp < ?
        ''', (cutoff_date.isoformat(),))
        conn.commit()
        conn.close()

# --- SambaNova clients (existing) ---
client_samba = OpenAI(
    base_url="https://api.sambanova.ai/v1",
    api_key=SAMBA_API_KEY 
)
client_samba_categorize = OpenAI(
    base_url="https://api.sambanova.ai/v1",
    api_key=SAMBA_CATEGORIZE_API_KEY 
)

def is_news_query_llm(message):
    prompt = (
        "Determine if this message is asking for NEWS CONTENT or just asking ABOUT news capabilities. "
        "NEWS CONTENT: 'What's happening in Kenya?', 'Tell me about protests', 'Latest on elections' "
        "CAPABILITY QUESTIONS: 'Can you access news?', 'Where do you get news?', 'How do you find news?' "
        "Only respond YES if they want actual news content, NO if they're asking about capabilities.\n\n"
        f"Message: {message}"
    )
    completion = client_samba_categorize.chat.completions.create(
        model="Meta-Llama-3.1-405B-Instruct",
        messages=[
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": prompt}
        ]
    )
    answer = completion.choices[0].message.content.strip().upper()
    return answer.startswith("YES")

def samba_general_chat(message):
    prompt = f"{message}"
    completion = client_samba.chat.completions.create(
        model="Meta-Llama-3.1-405B-Instruct",
        messages=[
            {"role": "system", "content": "You are a helpful, conversational assistant."},
            {"role": "user", "content": prompt}
        ]
    )
    return completion.choices[0].message.content.strip()

# --- User Preferences (stub for future expansion) ---
class UserPreferences:
    def __init__(self, db_path="user_preferences.db"):
        self.db_path = db_path
        self.init_preferences_db()
    def init_preferences_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS preferences (
                contact_name TEXT,
                topic TEXT,
                count INTEGER DEFAULT 1,
                PRIMARY KEY (contact_name, topic)
            )
        ''')
        conn.commit()
        conn.close()
    def track_interest(self, contact_name: str, topic: str):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO preferences (contact_name, topic, count) VALUES (?, ?, 1)
            ON CONFLICT(contact_name, topic) DO UPDATE SET count = count + 1
        ''', (contact_name, topic))
        conn.commit()
        conn.close()
    def get_user_interests(self, contact_name: str):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('''
            SELECT topic FROM preferences WHERE contact_name = ? ORDER BY count DESC LIMIT 3
        ''', (contact_name,))
        rows = cursor.fetchall()
        conn.close()
        return [row[0] for row in rows]
    def get_personalized_news_prompt(self, contact_name: str) -> str:
        interests = self.get_user_interests(contact_name)
        if interests:
            return f"Focus on topics related to: {', '.join(interests)}"
        return ""

# --- Conversation Ending Detection ---
def is_conversation_ending(message):
    ending_phrases = [
        "that's all for today", "bye", "goodbye", "talk later",
        "thanks, that's enough", "see you later", "gotta go"
    ]
    return any(phrase in message.lower() for phrase in ending_phrases)

def handle_conversation_ending(message):
    return "It was great chatting with you. Feel free to reach out whenever you'd like to discuss more news or topics. Have a great day!"

# --- Memory-enabled WhatsApp Bot ---
class MemoryEnabledWhatsAppBot:
    def __init__(self, config=None):
        self.config = config
        self.memory = ConversationMemory(max_context_messages=8)
        self.user_prefs = UserPreferences()
    def handle_message(self, contact_name: str, message: str):
        start_time = time.time()
        # 1. Conversation ending detection
        if is_conversation_ending(message):
            response = handle_conversation_ending(message)
            self.memory.add_message(contact_name, "user", message, "chat")
            self.memory.add_message(contact_name, "bot", response, "chat")
            self.log_conversation_metrics(contact_name, message, response, start_time)
            return response
        # 2. News/capability classification
        is_news = is_news_query_llm(message)
        message_type = "news" if is_news else "chat"
        self.memory.add_message(contact_name, "user", message, message_type)
        context = self.memory.get_conversation_context(contact_name)
        # 3. Smart follow-up and user preference tracking
        if is_news:
            self.user_prefs.track_interest(contact_name, message)
            response = search_qdrant_and_summarize(message)
            response += "\n\nWould you like me to look into any specific aspect of this topic?"
        elif self.is_capability_question(message):
            response = self.capability_explanation()
        else:
            response = self.samba_contextual_chat(context)
        # 4. Enhance response quality
        response = self.enhance_response_quality(response, message_type)
        self.memory.add_message(contact_name, "bot", response, message_type)
        self.log_conversation_metrics(contact_name, message, response, start_time)
        return response
    def samba_contextual_chat(self, context: List[Dict]) -> str:
        completion = client_samba.chat.completions.create(
            model="Meta-Llama-3.1-405B-Instruct",
            messages=context,
            max_tokens=500,
            temperature=0.7
        )
        return completion.choices[0].message.content.strip()
    def is_capability_question(self, message: str) -> bool:
        capability_keywords = [
            "can you access news", "where do you get news", "how do you find news", "do you browse news", "news sources", "how do you get news"
        ]
        return any(kw in message.lower() for kw in capability_keywords)
    def capability_explanation(self) -> str:
        return (
            "Yes, I can access and summarize news articles from reputable online sources such as People Daily, Standard Media, and others. "
            "If you'd like, I can show you some recent news articles or clarify my sources for a specific topic."
        )
    def enhance_response_quality(self, response: str, message_type: str) -> str:
        if message_type == "news":
            response += "\n\n📰 Sources: Verified news outlets"
        elif message_type == "chat":
            if random.random() < 0.1:
                response += " 😊"
        return response
    def log_conversation_metrics(self, contact_name: str, message: str, response: str, start_time: float):
        metrics = {
            "response_time": time.time() - start_time,
            "message_length": len(message),
            "response_length": len(response),
            "message_type": "news" if is_news_query_llm(message) else "chat",
            "timestamp": datetime.now().isoformat()
        }
        # For now, just print. You can log to file/db as needed.
        print(f"[METRICS] {contact_name}: {metrics}")
    def generate_contextual_response(self, contact_name: str, message: str, context: List[Dict]) -> str:
        if is_news_query_llm(message):
            response = search_qdrant_and_summarize(message)
            response += "\n\nWould you like me to look into any specific aspect of this topic?"
        else:
            response = self.samba_contextual_chat(context)
        return response

# --- WhatsApp Selenium functions (existing) ---
def open_whatsapp_and_select_contact(contact_name, driver_path, brave_path):
    options = Options()
    options.binary_location = brave_path
    service = Service(driver_path)
    driver = webdriver.Chrome(service=service, options=options)
    driver.get("https://web.whatsapp.com/")
    input("Scan the QR code in the browser, then press Enter here to continue...")
    search_box = driver.find_element(By.XPATH, '//div[@contenteditable="true"][@data-tab="3"]')
    search_box.click()
    search_box.send_keys(contact_name)
    time.sleep(2)
    search_box.send_keys(Keys.ENTER)
    time.sleep(2)
    return driver

def send_whatsapp_message(driver, message):
    message_box = driver.find_element(By.XPATH, '//div[@contenteditable="true"][@data-tab="10"]')
    for line in message.split('\n'):
        message_box.send_keys(line)
        message_box.send_keys(Keys.SHIFT + Keys.ENTER)
    message_box.send_keys(Keys.ENTER)
    time.sleep(2)

def get_last_incoming_message(driver):
    messages = driver.find_elements(By.CSS_SELECTOR, "div.message-in")
    if messages:
        try:
            text_elem = messages[-1].find_element(By.CSS_SELECTOR, "span.selectable-text span")
            return text_elem.text
        except Exception:
            return messages[-1].text
    return None

def remove_non_bmp(text):
    """Remove characters outside the Basic Multilingual Plane (BMP) for ChromeDriver compatibility."""
    return ''.join(c for c in text if ord(c) <= 0xFFFF)

if __name__ == "__main__":
    contact_name = "myy"  # Change as needed
    driver_path = "C:/Users/Rono/Desktop/Ai agent trial/chromedriver.exe"
    brave_path = "C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe"
    driver = open_whatsapp_and_select_contact(contact_name, driver_path, brave_path)
    print("Waiting for new messages...")
    last_seen_msg = None
    # --- Use memory-enabled bot ---
    memory_bot = MemoryEnabledWhatsAppBot()
    try:
        while True:
            last_msg = get_last_incoming_message(driver)
            if last_msg and last_msg != last_seen_msg:
                print(f"New message from {contact_name}: {last_msg}")
                response = memory_bot.handle_message(contact_name, last_msg)
                send_whatsapp_message(driver, remove_non_bmp(response))
                last_seen_msg = last_msg
            time.sleep(5)
    except KeyboardInterrupt:
        print("Exiting...")
    driver.quit()

