from flask import Flask

app = Flask(__name__)

@app.route("/")
def home():
    return "Do Brazil Bot is running!"
