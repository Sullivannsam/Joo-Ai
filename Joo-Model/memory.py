from datetime import datetime

history = []


def add_history(user, assistant):
    history.append({
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "user": user,
        "assistant": assistant
    })


def get_history(limit=10):
    return history[-limit:]


def clear_history():
    history.clear()
