import os
import psutil
from datetime import datetime
from memory import get_history, clear_history


def handle_command(command):

    if command == "/help":
        print("""
Commands:
/help     Show commands
/history  Show chat history
/clear    Clear chat history
/status   Show RAM usage
/time     Show Cambodia time
/exit     Exit Joo
""")

    elif command == "/history":
        for item in get_history():
            print(f"\nUser: {item['user']}")
            print(f"Joo : {item['assistant']}")

    elif command == "/time":
        now = datetime.now()

        hour = now.hour

        # Day / Night logic
        if 6 <= hour < 18:
            day_state = "メ Day"
        else:
            day_state = "☾ Night"

        time_str = now.strftime("%H:%M:%S")
        date_str = now.strftime("%d : %m : %Y")

        print(f"""
      ────────────Current Time────────────

      Time: ("{time_str}")
      Date: ({date_str})

      Daytime: {day_state}
╰┈➤   ────────────────•───────────────────
""")

    elif command == "/clear":
        clear_history()
        os.system("clear")

    elif command == "/status":
        ram = psutil.virtual_memory()
        print(f"RAM Usage: {ram.percent}%")

    elif command == "/exit":
        print("Shutting down Joo...")
        exit()

    else:
        print("Unknown command")
