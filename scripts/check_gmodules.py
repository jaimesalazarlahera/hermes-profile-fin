import importlib
mods = [
    "gspread", "gspreadplus", "google", "googleapiclient", "googleapiclient.discovery",
    "google.auth", "google.oauth2", "google.oauthclient", "apiclient",
    "googleapiclient.http", "googleapiclient.errors",
]
for m in mods:
    try:
        mod = importlib.import_module(m)
        print("OK  ", m, " ->", getattr(mod, "__version__", "?"))
    except Exception as e:
        print("MISS", m, "->", type(e).__name__)
