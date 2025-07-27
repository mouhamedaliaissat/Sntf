from flask import Flask, jsonify
from threading import Thread
import logging
import time
import os

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask('')

@app.route('/')
def home():
    return "🚂 Train Schedule Bot is alive and running!"

@app.route('/health')
def health_check():
    return jsonify({
        "status": "healthy", 
        "timestamp": time.time(),
        "uptime": time.time() - start_time
    })

@app.route('/ping')
def ping():
    return "pong"

def run():
    try:
        # Disable Flask logging to reduce noise
        log = logging.getLogger('werkzeug')
        log.disabled = True
        
        app.run(
            host='0.0.0.0', 
            port=8080, 
            debug=False, 
            use_reloader=False,
            threaded=True
        )
        logger.info("✅ Keep-alive server started successfully")
    except Exception as e:
        logger.error(f"❌ Keep-alive server error: {e}")
        # Try to restart after a delay
        time.sleep(5)
        run()

def keep_alive():
    global start_time
    start_time = time.time()
    
    server_thread = Thread(target=run, name="KeepAliveServer")
    server_thread.daemon = True
    server_thread.start()
    
    logger.info("🔄 Keep-alive server started on port 8080")
    
    # Give the server a moment to start
    time.sleep(2)
    
    return server_thread
