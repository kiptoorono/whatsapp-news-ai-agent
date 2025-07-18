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


load_dotenv("C:/Users/Rono/Desktop/Ai agent trial/.env")

SAMBA_API_KEY = os.getenv("SAMBA_API_KEY")
SAMBA_CATEGORIZE_API_KEY = os.getenv("SAMBA_CATEGORIZE_API_KEY")

def open_whatsapp_and_select_contact(contact_name, driver_path, brave_path):
    options = Options()
    options.binary_location = brave_path
    service = Service(driver_path)
    driver = webdriver.Chrome(service=service, options=options)
    driver.get("https://web.whatsapp.com/")
    input("Scan the QR code in the browser, then press Enter here to continue...")
    # Search for the contact
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
        message_box.send_keys(Keys.SHIFT + Keys.ENTER)  # New line
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

# SambaNova client for general chat and summarization (existing)
client_samba = OpenAI(
    base_url="https://api.sambanova.ai/v1",
    api_key=SAMBA_API_KEY 
)
# SambaNova client for categorization/classification (new)
client_samba_categorize = OpenAI(
    base_url="https://api.sambanova.ai/v1",
    api_key=SAMBA_CATEGORIZE_API_KEY 
)

def is_news_query_llm(message):
    prompt = (
        "You are an AI assistant. Determine if the following user message is a news-related question. "
        "If it is about current events, politics, government, education, protests, or similar topics, answer YES. "
        "If it is a general chat, joke, or not news-related, answer NO. "
        "Respond with only YES or NO.\n\n"
        f"User: {message}"
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

if __name__ == "__main__":
    contact_name = "myy"  # Change as needed
    driver_path = "C:/Users/Rono/Desktop/Ai agent trial/chromedriver.exe"
    brave_path = "C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe"
    driver = open_whatsapp_and_select_contact(contact_name, driver_path, brave_path)
    print("Waiting for new messages...")
    last_seen_msg = None
    try:
        while True:
            last_msg = get_last_incoming_message(driver)
            if last_msg and last_msg != last_seen_msg:
                print(f"New message from {contact_name}: {last_msg}")
                if is_news_query_llm(last_msg):
                    response = search_qdrant_and_summarize(last_msg)
                else:
                    response = samba_general_chat(last_msg)
                send_whatsapp_message(driver, response)
                last_seen_msg = last_msg
            time.sleep(5)
    except KeyboardInterrupt:
        print("Exiting...")
    driver.quit()

print("SAMBA_API_KEY:", SAMBA_API_KEY)
print("SAMBA_CATEGORIZE_API_KEY:", SAMBA_CATEGORIZE_API_KEY)