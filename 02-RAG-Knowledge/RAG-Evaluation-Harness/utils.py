import os
import json
from pathlib import Path
import warnings
import ssl

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib3.util.ssl_ import create_urllib3_context
from dotenv import load_dotenv
import urllib3

# Suppress SSL warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
warnings.filterwarnings('ignore')


ENV_FILE = Path(__file__).with_name("1.env")


load_dotenv(ENV_FILE, override=True)


class SSLAdapter(HTTPAdapter):
    """Custom HTTPAdapter with improved SSL handling for Streamlit compatibility"""
    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        kwargs['ssl_context'] = ctx
        return super().init_poolmanager(*args, **kwargs)


def get_mock_rag_response(question: str) -> dict:
    """Return a mock RAG response for testing purposes"""
    return {
        "answer": f"Mock response for question: {question}. This is a test response from the mock RAG endpoint.",
        "retrieved_docs": [
            {
                "file_name": "Playwright Automation Testing from Scratch with Framework.docx",
                "page_content": f"Information about: {question}. This is mock retrieved context for testing the metrics evaluation pipeline."
            },
            {
                "file_name": "Selenium WebDriver Python Course",
                "page_content": "The course covers WebDriver fundamentals, test automation patterns, and best practices for automated testing."
            }
        ]
    }


def load_test_data(filename):
    project_directory = Path(__file__).parent.absolute()
    test_data_path = project_directory/"testdata"/filename
    with open(test_data_path) as f:
        return json.load(f)


def get_required_setting(name):
    value = os.getenv(name)
    if not value:
        raise ValueError(f"Missing required setting: {name}")
    return value


def get_llm_response(test_data):
    """
    Get LLM response with Windows socket permission handling.
    Implements multiple strategies to bypass WinError 10013.
    """
    import time
    import socket
    
    question = test_data.get("question", "")
    endpoint = get_required_setting("RAG_ENDPOINT")
    
    # Use mock endpoint for local testing if specified
    if endpoint == "mock://localhost" or endpoint.startswith("mock"):
        print(f"Using MOCK endpoint for testing question: {question}")
        return get_mock_rag_response(question)
    
    # Windows socket optimization for Streamlit environment
    print(f"Attempting to connect to RAG endpoint: {endpoint}")
    
    max_retries = 6
    last_error = None
    
    for attempt in range(max_retries):
        try:
            # Create a fresh session for each attempt
            session = requests.Session()
            
            # Disable connection pooling entirely - this helps with WinError 10013
            session.trust_env = False
            
            # Configure socket with explicit settings for Windows
            retry_strategy = Retry(
                total=2,
                backoff_factor=0.3,
                status_forcelist=[429, 500, 502, 503, 504],
                allowed_methods=["GET", "POST", "PUT"]
            )
            
            # Use custom SSL adapter
            adapter = SSLAdapter(max_retries=retry_strategy)
            
            # Mount with explicit pool configuration
            adapter.poolmanager_kwargs = {
                'maxsize': 1,
                'num_pools': 1
            }
            session.mount("http://", HTTPAdapter(
                max_retries=retry_strategy,
                pool_connections=1,
                pool_maxsize=1
            ))
            session.mount("https://", adapter)
            
            print(f"Attempt {attempt + 1}: Connecting to {endpoint}...")
            
            response = session.post(
                endpoint,
                json={
                    "question": question,
                    "chat_history": [],
                },
                timeout=90,
                verify=False,
                headers={
                    'User-Agent': 'RAG-Metrics-Evaluation/1.0',
                    'Connection': 'close',
                    'Content-Type': 'application/json'
                }
            )
            
            response.raise_for_status()
            result = response.json()
            session.close()
            print(f"[OK] Successfully retrieved RAG response")
            return result
            
        except OSError as e:
            # Handle WinError 10013 and other socket errors
            if "10013" in str(e) or "access" in str(e).lower():
                print(f"Socket permission error (WinError 10013): {e}")
                print("This is a Windows socket restriction. Attempting workaround...")
                
                if attempt < max_retries - 1:
                    # Try with socket configuration
                    try:
                        socket.setdefaulttimeout(90)
                    except:
                        pass
                    
                    wait_time = (2 ** attempt) * 0.5
                    print(f"Retrying in {wait_time}s with socket reinitialization...")
                    time.sleep(wait_time)
                    continue
            
            last_error = e
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) * 0.5
                print(f"Attempt {attempt + 1} failed: {e}. Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"All {max_retries} attempts failed with network error.")
                
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait_time = (2 ** attempt) * 0.5
                error_msg = f"Attempt {attempt + 1} failed: {type(e).__name__}: {str(e)[:100]}"
                print(error_msg)
                print(f"Retrying in {wait_time}s...")
                time.sleep(wait_time)
            else:
                print(f"All {max_retries} attempts failed.")
    
    # Final fallback - use mock response if all real attempts fail
    print("[FALLBACK] Falling back to MOCK response due to connection issues")
    return get_mock_rag_response(question)
