import sys
import os

# --- ADD THESE TWO LINES FOR DEBUGGING ---
sys.stderr.write(f"--- WSGI using Python: {sys.executable}\n")
sys.stderr.write(f"--- WSGI Python path: {sys.path}\n")

# Add your project's directory to the Python path
project_home = os.path.dirname(__file__)
if project_home not in sys.path:
    sys.path.insert(0, project_home)

# Activate your virtual environment if you use one
activate_this = os.path.join(project_home, 'venv', 'bin', 'activate_this.py') # Adjust 'venv' if different
try:
    with open(activate_this) as f:
        exec(f.read(), dict(__file__=activate_this))
except FileNotFoundError:
    # Handle error: virtual environment not found
    pass

# Import your Flask app instance
# Assuming your Flask app instance is named 'app' in 'app.py'
from app import app as application



