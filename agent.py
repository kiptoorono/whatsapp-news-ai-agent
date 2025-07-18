# --- Web scraping and summarization code (commented out for now) ---
'''
import requests
from bs4 import BeautifulSoup
import json

def fetch_peopledaily_headlines():
    # ... (scraping code)
    pass

def fetch_article_content(url):
    # ... (scraping code)
    pass

def summarize_and_categorize_with_ollama(text, model="gemma3"):
    # ... (Ollama code)
    pass
'''
# --- End of web scraping and summarization code ---

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import time
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

def send_whatsapp_message(
    contact_name,
    message,
    driver_path="C:/Users/Rono/Desktop/Ai agent trial/chromedriver.exe",
    brave_path="C:/Program Files/BraveSoftware/Brave-Browser/Application/brave.exe"
):
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

    # Find the message box and send the message
    message_box = driver.find_element(By.XPATH, '//div[@contenteditable="true"][@data-tab="10"]')
    for line in message.split('\n'):
        message_box.send_keys(line)
        message_box.send_keys(Keys.SHIFT + Keys.ENTER)  # New line
    message_box.send_keys(Keys.ENTER)
    time.sleep(2)
    driver.quit()

if __name__ == "__main__":
    # Read the file content into news_text
    with open("summarized_news.txt", "r", encoding="utf-8") as f:
        news_text = f.read()

    contact_name = "myy"
    send_whatsapp_message(contact_name, news_text)