
from flask import Flask, render_template
from rclone_manager.scheduler import Scheduler

app = Flask(__name__)
scheduler = Scheduler()

@app.route("/")
def index():
    return render_template("index.html")

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
