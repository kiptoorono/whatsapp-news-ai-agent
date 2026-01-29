from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import time
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from openai import OpenAI
from quantsearch import NewsSearchAgent
import os
from dotenv import load_dotenv
# --- Conversation Memory Imports ---
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List
from dataclasses import dataclass
import random
import re
from difflib import SequenceMatcher
from typing import List, Dict, Tuple, Optional
import json


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

# --- Intent Classification System ---
class IntentClassifier:
    def __init__(self, config_path: str = "intent_config.json"):
        self.config_path = config_path
        self.intents = {}
        self.news_patterns = []
        self.settings = {}
        self.load_config()
    
    def load_config(self):
        """Load intent patterns from configuration file"""
        try:
            if os.path.exists(self.config_path):
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.intents = config.get('intents', {})
                    self.news_patterns = config.get('news_patterns', [])
                    self.settings = config.get('settings', {})
            else:
                # Fallback to default configuration
                self._load_default_config()
        except Exception as e:
            print(f"Warning: Could not load config from {self.config_path}: {e}")
            self._load_default_config()
    
    def _load_default_config(self):
        """Load default configuration if config file is not available"""
        self.intents = {
            'date_request': {
                'patterns': [
                    r'\b(what|when|tell me|give me|show me|what\'s|what is)\s+(day|date|today|now)\b',
                    r'\b(today|now)\s+(date|day)\b',
                    r'\b(date|day)\s+(today|now)\b',
                    r'\bcurrent\s+date\b',
                    r'\btoday\'s\s+date\b',
                    r'\bdate\s+now\b',
                    r'\bwhat\s+date\s+is\s+it\b',
                    r'\bcan\s+you\s+(tell|give|show)\s+me\s+the\s+date\b'
                ],
                'keywords': ['date', 'today', 'day', 'now', 'current'],
                'threshold': 0.6
            },
            'name_request': {
                'patterns': [
                    r'\b(what|tell me|what\'s|what is)\s+(your|your name|should i call you)\b',
                    r'\b(call|name)\s+you\b',
                    r'\bdo\s+you\s+have\s+a\s+name\b',
                    r'\bwhat\s+can\s+i\s+call\s+you\b',
                    r'\byour\s+name\b'
                ],
                'keywords': ['name', 'call', 'you', 'your'],
                'threshold': 0.6
            },
            'capability_question': {
                'patterns': [
                    r'\b(are you|do you|can you)\s+(aware|know|access|get|find|browse|read)\b',
                    r'\b(where|how)\s+do\s+you\s+(get|find|access|know)\b',
                    r'\b(news sources|information sources)\b',
                    r'\bintelligently\s+aware\b',
                    r'\bdo\s+you\s+have\s+access\b',
                    r'\bcan\s+you\s+read\b'
                ],
                'keywords': ['aware', 'know', 'access', 'get', 'find', 'browse', 'read', 'sources', 'information'],
                'threshold': 0.5
            },
            'correction': {
                'patterns': [
                    r'\b(no|wrong|incorrect|actually|but|however)\b',
                    r'\b(that\'s|that is)\s+(wrong|not right|incorrect)\b',
                    r'\byou\'re\s+wrong\b',
                    r'\bthat\'s\s+not\s+(right|correct)\b'
                ],
                'keywords': ['no', 'wrong', 'incorrect', 'actually', 'but', 'however'],
                'threshold': 0.7
            },
            'follow_up': {
                'patterns': [
                    r'\b(tell me|explain|elaborate)\s+more\b',
                    r'\b(what about|more details|what else)\b',
                    r'\b(and also|also|additionally)\b',
                    r'\b(what do you think|your opinion|your take)\b',
                    r'\blike\s+explain\b',
                    r'\bcan\s+you\s+(elaborate|explain)\b'
                ],
                'keywords': ['more', 'further', 'else', 'also', 'think', 'opinion', 'explain', 'elaborate'],
                'threshold': 0.5
            }
        }
        self.news_patterns = [
            r'\b(tell me|what\'s|what is)\s+(happening|latest|current|trending|breaking)\b',
            r'\b(latest|current|trending|breaking|recent)\s+(news|developments|updates)\b',
            r'\b(protest|election|government|politics|economy|business)\b',
            r'\b(kenya|kenyan)\s+(news|politics|economy)\b',
            r'\bwhat\s+(about|regarding|concerning)\b'
        ]
        self.settings = {
            'pattern_weight': 0.7,
            'keyword_weight': 0.3,
            'default_threshold': 0.5,
            'fuzzy_match_threshold': 0.8
        }
    
    def reload_config(self):
        """Reload configuration from file"""
        self.load_config()
    
    def classify_intent(self, message: str) -> Tuple[str, float]:
        """
        Classify the intent of a message with confidence score
        Returns: (intent_name, confidence_score)
        """
        if not message or not message.strip():
            return (None, 0.0)
        
        message_lower = message.lower().strip()
        
        best_intent = None
        best_score = 0.0
        
        for intent_name, intent_config in self.intents.items():
            score = self._calculate_intent_score(message_lower, intent_config)
            threshold = intent_config.get('threshold', self.settings.get('default_threshold', 0.5))
            if score > best_score and score >= threshold:
                best_score = score
                best_intent = intent_name
        
        return (best_intent, best_score)
    
    def _calculate_intent_score(self, message: str, intent_config: Dict) -> float:
        """Calculate confidence score for an intent"""
        pattern_score = self._pattern_match_score(message, intent_config['patterns'])
        keyword_score = self._keyword_match_score(message, intent_config['keywords'])
        
        # Get weights from settings
        pattern_weight = self.settings.get('pattern_weight', 0.7)
        keyword_weight = self.settings.get('keyword_weight', 0.3)
        
        # Combine pattern and keyword scores with weights
        return (pattern_score * pattern_weight) + (keyword_score * keyword_weight)
    
    def _pattern_match_score(self, message: str, patterns: List[str]) -> float:
        """Score based on regex pattern matches"""
        max_score = 0.0
        for pattern in patterns:
            try:
                matches = re.findall(pattern, message, re.IGNORECASE)
                if matches:
                    # Score based on how much of the pattern matched
                    pattern_length = len(pattern.replace(r'\b', '').replace(r'\s+', ' '))
                    match_ratio = sum(len(match) for match in matches) / len(message)
                    score = min(1.0, match_ratio * 2)  # Boost score for good matches
                    max_score = max(max_score, score)
            except re.error:
                # Skip invalid regex patterns
                continue
        return max_score
    
    def _keyword_match_score(self, message: str, keywords: List[str]) -> float:
        """Score based on keyword similarity"""
        words = message.split()
        if not words:
            return 0.0
        
        total_score = 0.0
        fuzzy_threshold = self.settings.get('fuzzy_match_threshold', 0.8)
        
        for word in words:
            best_keyword_score = 0.0
            for keyword in keywords:
                # Use fuzzy matching for keyword similarity
                similarity = SequenceMatcher(None, word, keyword).ratio()
                if similarity >= fuzzy_threshold:
                    best_keyword_score = max(best_keyword_score, similarity)
            total_score += best_keyword_score
        
        return total_score / len(words)
    
    def classify_multiple_intents(self, message: str) -> List[Tuple[str, float]]:
        """Classify multiple intents in a single message"""
        if not message or not message.strip():
            return []
        
        message_lower = message.lower().strip()
        detected_intents = []
        
        for intent_name, intent_config in self.intents.items():
            score = self._calculate_intent_score(message_lower, intent_config)
            threshold = intent_config.get('threshold', self.settings.get('default_threshold', 0.5))
            if score >= threshold:
                detected_intents.append((intent_name, score))
        
        # Sort by confidence score
        detected_intents.sort(key=lambda x: x[1], reverse=True)
        return detected_intents
    
    def is_news_pattern(self, message: str) -> bool:
        """Check if message matches news patterns"""
        message_lower = message.lower()
        for pattern in self.news_patterns:
            try:
                if re.search(pattern, message_lower, re.IGNORECASE):
                    return True
            except re.error:
                continue
        return False

# Initialize the intent classifier
intent_classifier = IntentClassifier()

def is_news_query_llm(message):
    # First, check for capability questions that should NOT trigger news search
    intent, confidence = intent_classifier.classify_intent(message)
    
    if intent == 'capability_question':
        return False
    
    # Then check for actual news content requests using the intent classifier
    if intent_classifier.is_news_pattern(message):
        return True
    
    # For ambiguous cases, use the LLM classifier
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

# --- Date Awareness Function ---
def get_current_date():
    """Get the current date in a readable format"""
    from datetime import datetime
    now = datetime.now()
    return now.strftime("%B %d, %Y")

def is_date_question(message):
    """Check if the message is asking about the current date"""
    intent, confidence = intent_classifier.classify_intent(message)
    return intent == 'date_request'

def is_name_question(message):
    """Check if the message is asking about the bot's name"""
    intent, confidence = intent_classifier.classify_intent(message)
    return intent == 'name_request'

def is_correction(message):
    """Detect if the user is correcting the bot"""
    intent, confidence = intent_classifier.classify_intent(message)
    return intent == 'correction'

def is_follow_up_question(message):
    """Detect if this is a follow-up question to previous content"""
    intent, confidence = intent_classifier.classify_intent(message)
    return intent == 'follow_up'

def handle_multiple_intents(message: str) -> str:
    """Handle messages with multiple intents"""
    intents = intent_classifier.classify_multiple_intents(message)
    
    if len(intents) == 0:
        return None  # No specific intent detected
    
    if len(intents) == 1:
        return None  # Single intent, handled by other functions
    
    # Handle multiple intents
    responses = []
    
    for intent, confidence in intents:
        if intent == 'date_request':
            responses.append(f"Today is {get_current_date()}.")
        elif intent == 'name_request':
            responses.append("I don't have a personal name, but you can call me Assistant or AI for short.")
        elif intent == 'capability_question':
            responses.append("I'm an AI assistant with access to news articles from Kenyan sources.")
    
    if responses:
        return " ".join(responses)
    
    return None

def samba_general_chat(message):
    # First, check for multiple intents
    multi_intent_response = handle_multiple_intents(message)
    if multi_intent_response:
        return multi_intent_response
    
    # Handle specific question types using intent classification
    intent, confidence = intent_classifier.classify_intent(message)
    
    if intent == 'date_request':
        return f"Today is {get_current_date()}."
    
    if intent == 'name_request':
        return "I don't have a personal name, but you can call me Assistant or AI for short. Some people also like to give me nicknames, so feel free to get creative if you'd like!"
    
    if intent == 'capability_question':
        return (
            "I'm an AI assistant with access to news articles from sources like People Daily, Standard Media, and other Kenyan news outlets. "
            "I can search through and summarize recent news content for you. However, I don't have real-time access to current events "
            "or personal experiences - my knowledge comes from the articles in my database. What would you like to know about?"
        )
    
    if intent == 'correction':
        return handle_correction(message)
    
    # Default general chat response
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

def handle_follow_up_question(message, context):
    """Handle follow-up questions with more detailed responses"""
    # Extract the topic from the follow-up question
    topic_indicators = ["about", "regarding", "on", "concerning"]
    words = message.lower().split()
    
    # Find the topic by looking for words after follow-up indicators
    topic = ""
    for i, word in enumerate(words):
        if word in ["more", "further", "else", "also"] and i + 1 < len(words):
            topic = " ".join(words[i+1:])
            break
    
    if topic:
        # Search for more specific information about the topic
        search_query = f"Kenya {topic}"
        return search_query
    else:
        # Generic follow-up response
        return "I'd be happy to provide more details. Could you specify what aspect you'd like me to elaborate on?"

def handle_correction(message):
    """Handle user corrections gracefully"""
    return (
        "Thank you for the correction! I appreciate you helping me provide accurate information. "
        "I'll keep that in mind for our conversation. Is there anything else you'd like to discuss?"
    )

# --- Memory-enabled WhatsApp Bot ---
class MemoryEnabledWhatsAppBot:
    def __init__(self, config=None):
        self.config = config
        self.memory = ConversationMemory(max_context_messages=8)
        self.user_prefs = UserPreferences()
        # Initialize the news search agent
        self.news_agent = NewsSearchAgent(
            qdrant_host="localhost",
            qdrant_port=6333,
            collection_name="peopledaily_articles",
            samba_api_key=SAMBA_API_KEY
        )
    def handle_message(self, contact_name: str, message: str):
        start_time = time.time()
        
        # 1. Conversation ending detection
        if is_conversation_ending(message):
            response = handle_conversation_ending(message)
            self.memory.add_message(contact_name, "user", message, "chat")
            self.memory.add_message(contact_name, "bot", response, "chat")
            self.log_conversation_metrics(contact_name, message, response, start_time)
            return response
        
        # 2. Get intent classification
        intent, confidence = intent_classifier.classify_intent(message)
        
        # 3. Handle special intents that don't need news classification
        special_intents = ['date_request', 'name_request', 'capability_question', 'correction']
        if intent in special_intents:
            response = samba_general_chat(message)
            message_type = "chat"
            self.memory.add_message(contact_name, "user", message, message_type)
            self.memory.add_message(contact_name, "bot", response, message_type)
            self.log_conversation_metrics(contact_name, message, response, start_time)
            return response
        
        # 4. Check for follow-up questions
        context = self.memory.get_conversation_context(contact_name)
        if intent == 'follow_up':
            # Check if the previous message was news-related
            recent_messages = self.memory.current_conversations.get(contact_name, [])
            if recent_messages and recent_messages[-1].message_type == "news":
                # This is a follow-up to news content
                search_query = handle_follow_up_question(message, context)
                if search_query and not search_query.startswith("I'd be happy"):
                    response = self.news_agent.search_and_summarize_time_aware(search_query)
                    response += "\n\nIs there anything specific about this topic you'd like me to explore further?"
                else:
                    response = search_query
                message_type = "news"
            else:
                # General follow-up question
                response = samba_general_chat(message)
                message_type = "chat"
        else:
            # 5. News/capability classification for remaining cases
            is_news = is_news_query_llm(message)
            message_type = "news" if is_news else "chat"
            
            # 6. Generate appropriate response
            if is_news:
                self.user_prefs.track_interest(contact_name, message)
                response = self.news_agent.search_and_summarize_time_aware(message)
                response += "\n\nWould you like me to look into any specific aspect of this topic?"
            else:
                response = samba_general_chat(message)
        
        # 7. Store in memory and enhance response
        self.memory.add_message(contact_name, "user", message, message_type)
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
            "I'm an AI assistant with access to a database of news articles from Kenyan sources like People Daily, Standard Media, and others. "
            "I can search through and summarize recent news content for you. However, I should clarify that:\n\n"
            "• I don't have real-time access to current events\n"
            "• My knowledge comes from articles in my database\n"
            "• I can't browse the internet or access live information\n"
            "• I can provide analysis and context based on available articles\n\n"
            "If you'd like to test my news capabilities, feel free to ask about any topic and I'll search my database for relevant articles!"
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
            response = self.news_agent.search_and_summarize_time_aware(message)
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

