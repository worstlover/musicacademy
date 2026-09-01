import requests
import json
import time
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django
django.setup()

from django.core.cache import cache
from django.test import Client

TOKEN = '1989571340:qMlMGrxZa47eDBuPfLd5CY6Me4MGrIjJ98U'
API_URL = f"https://tapi.bale.ai/bot{TOKEN}"

def process_update(update):
    """ارسال update به webhook handler"""
    client = Client()
    response = client.post(
        '/bot/webhook/',
        data=json.dumps(update),
        content_type='application/json'
    )
    print(f"✅ Processed: {response.status_code}")

def main():
    offset = 0
    print("🚀 شروع polling...")
    
    while True:
        try:
            response = requests.get(
                f"{API_URL}/getUpdates",
                params={"offset": offset, "timeout": 30}
            )
            
            if response.status_code == 200:
                updates = response.json().get('result', [])
                
                for update in updates:
                    print(f"\n📨 New update: {json.dumps(update, ensure_ascii=False)[:200]}")
                    
                    # پردازش
                    process_update(update)
                    
                    offset = update['update_id'] + 1
            
            time.sleep(1)
            
        except KeyboardInterrupt:
            print("\n⏹️ Polling stopped.")
            break
        except Exception as e:
            print(f"❌ Error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()