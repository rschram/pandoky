# pandoky/plugins/auth_plugin.py

import os
import re
import json
from flask import request, render_template, redirect, url_for, session, flash, g, Blueprint, current_app
from flask_mail import Message
from werkzeug.security import generate_password_hash, check_password_hash
import secrets # For generating secure tokens
from datetime import datetime, timedelta

# --- Configuration ---
USERS_FILENAME = "auth_users.json" # User data file
AUTH_BLUEPRINT_NAME = 'auth_plugin'
DEFAULT_HASH_METHOD = 'pbkdf2:sha256' 
TOKEN_EXPIRATION_HOURS = 24 # For verification and password reset tokens

# --- User Data Management ---
def get_users_file_path(app_instance):
    data_dir = app_instance.config.get('DATA_DIR', os.path.join(app_instance.root_path, 'data'))
    return os.path.join(data_dir, USERS_FILENAME)

def load_users(app_instance):
    users_file = get_users_file_path(app_instance)
    if os.path.exists(users_file):
        try:
            with open(users_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            app_instance.logger.error(f"AuthPlugin: Error loading users file {users_file}: {e}")
            return {} 
    return {} 

def save_users(app_instance, users_data):
    users_file = get_users_file_path(app_instance)
    try:
        with open(users_file, 'w', encoding='utf-8') as f:
            json.dump(users_data, f, indent=4, ensure_ascii=False)
        app_instance.logger.info(f"AuthPlugin: User data saved to {users_file}")
    except Exception as e:
        app_instance.logger.error(f"AuthPlugin: Error saving users file {users_file}: {e}")

def generate_token():
    return secrets.token_urlsafe(32)

def get_token_expiry():
    return (datetime.utcnow() + timedelta(hours=TOKEN_EXPIRATION_HOURS)).isoformat()

# --- Blueprint for Auth Routes ---
auth_bp = Blueprint(AUTH_BLUEPRINT_NAME, __name__, template_folder='../templates/html/auth') # New template subfolder

# # --- Simulated Email Sending ---
# def send_verification_email(app_instance, email, username, token):
#     verification_link = url_for(f"{AUTH_BLUEPRINT_NAME}.verify_email_route", token=token, _external=True)
#     subject = "Pandoky - Verify Your Email Address"
#     body = (
#         f"Hi {username},\n\n"
#         f"Thanks for registering with Pandoky! Please verify your email address by clicking the link below:\n"
#         f"{verification_link}\n\n"
#         f"This link will expire in {TOKEN_EXPIRATION_HOURS} hours.\n\n"
#         f"If you did not register for Pandoky, please ignore this email.\n\n"
#         f"Thanks,\nThe Pandoky Team"
#     )
#     app_instance.logger.info(f"SIMULATED EMAIL to {email}\nSubject: {subject}\nBody:\n{body}")
#     print(f"\n--- SIMULATED EMAIL to {email} ---\nSubject: {subject}\nBody:\n{body}\n-----------------------------\n")

# def send_password_reset_email(app_instance, email, username, token):
#     reset_link = url_for(f"{AUTH_BLUEPRINT_NAME}.reset_password_with_token_route", token=token, _external=True)
#     subject = "Pandoky - Password Reset Request"
#     body = (
#         f"Hi {username},\n\n"
#         f"You requested a password reset for your Pandoky account. Click the link below to set a new password:\n"
#         f"{reset_link}\n\n"
#         f"This link will expire in {TOKEN_EXPIRATION_HOURS} hours.\n\n"
#         f"If you did not request a password reset, please ignore this email.\n\n"
#         f"Thanks,\nThe Pandoky Team"
#     )
#     app_instance.logger.info(f"SIMULATED EMAIL to {email}\nSubject: {subject}\nBody:\n{body}")
#     print(f"\n--- SIMULATED EMAIL to {email} ---\nSubject: {subject}\nBody:\n{body}\n-----------------------------\n")
# # ------------------------------------------

# ----- Live email sending ------------
def send_email(app_instance, subject, recipients, text_body, html_body=None):
    """Helper function to send an email."""
    # Get the Mail instance from the app. It should have been initialized in app.py.
    # Using current_app might be more robust if app_instance isn't always the fully initialized app
    # mail_extension = getattr(current_app, 'extensions', {}).get('mail')
    # A simpler way if mail is attached to app:
    mail_extension = getattr(app_instance, 'extensions', {}).get('mail')
    if not mail_extension:
        app_instance.logger.error("AuthPlugin: Flask-Mail not initialized on app instance. Cannot send email.")
        # Fallback to console print for critical failure
        print(f"\n--- FALLBACK (MAIL NOT INIT) EMAIL to {recipients} ---\nSubject: {subject}\nBody:\n{text_body}\n-----------------------------\n")
        return

    # MAIL_DEFAULT_SENDER can be a string or a tuple (name, address)
    sender = app_instance.config.get('MAIL_DEFAULT_SENDER', 'no-reply@pandoky.example.com')
    
    msg = Message(subject, sender=sender, recipients=recipients)
    msg.body = text_body
    if html_body:
        msg.html = html_body
    try:
        if not app_instance.config.get('MAIL_SUPPRESS_SEND', False): # Check if sending is suppressed
            mail_extension.send(msg)
            app_instance.logger.info(f"AuthPlugin: Email sent to {recipients} with subject '{subject}'")
        else:
            app_instance.logger.info(f"AuthPlugin: Email sending suppressed. Would send to {recipients} with subject '{subject}'")
            print(f"\n--- SIMULATED (MAIL_SUPPRESS_SEND=True) EMAIL to {recipients} ---\nSubject: {subject}\nBody:\n{text_body}\n-----------------------------\n")
    except Exception as e:
        app_instance.logger.error(f"AuthPlugin: Failed to send email to {recipients}: {e}", exc_info=True)
        # Fallback to console print on error
        print(f"\n--- FAILED EMAIL (see logs) to {recipients} ---\nSubject: {subject}\nBody:\n{text_body}\n-----------------------------\n")

def send_verification_email(app_instance, email, username, token):
    appname = app_instance.config.get('APP_NAME')
    verification_link = url_for(f"{AUTH_BLUEPRINT_NAME}.verify_email_route", token=token, _external=True)
    subject = f"{appname} - Verify your email address"
    text_body = render_template('auth/email/verify_email.txt', username=username, verification_link=verification_link, appname=appname)
    # You can create an HTML version of the email too for better formatting
    # html_body = render_template('auth/email/verify_email.html', username=username, verification_link=verification_link)
    send_email(app_instance, subject, [email], text_body) #, html_body=html_body)

def send_password_reset_email(app_instance, email, username, token):
    appname = app_instance.config.get('APP_NAME')
    reset_link = url_for(f"{AUTH_BLUEPRINT_NAME}.reset_password_with_token_route", token=token, _external=True)
    subject = f"{appname} - Password reset request"
    text_body =  render_template('auth/email/reset_password.txt', username=username, reset_link=reset_link, appname=appname) 
    send_email(app_instance, subject, [email], text_body) #, html_body=html_body)
# ------------------------------------------

def check_password(password):
    if len(password) < 8:
        return False

    has_uppercase = False
    has_number = False

    for c in password:
        if not has_uppercase and c.isupper():
            if has_number:
                return True
            has_uppercase = True
        elif not has_number and c.isdigit():
            if has_uppercase:
                return True
            has_number = True

    return False

# --- Routes ---
@auth_bp.route('/register', methods=['GET', 'POST'])
def register_route():
    app_instance = getattr(g, 'app', current_app._get_current_object())
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        if not username or not password or not email:
            flash("Username, email, and password are required.", "error")
            return render_template('register.html', title="Register", username='', email='')

        if not username.isalnum():
            flash("Username must consist of only letters and numbers.", "error")
            return render_template('register.html', title="Register", username='', email='')

        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email): 
            flash("Invalid email.", "error")
            return render_template('register.html', title="Register", username='', email='')

        if not check_password(password):
            flash("Password must contain at least one uppercase letter and one numeral and be at least 8 characters long.", "error")
            return render_template('register.html', title="Register", username=username, email=email)
           
        
        users = load_users(app_instance)
        if username in users:
            flash("Username already exists. Please choose another.", "error")
            return render_template('register.html', title="Register", username=username, email=email)
        
        for u_data in users.values(): # Check if email is already in use
            if u_data.get('email') == email:
                flash("Email address already registered. Please use a different email or try logging in.", "error")
                return render_template('register.html', title="Register", username=username, email=email)

        verification_token = generate_token()
        users[username] = {
            "email": email,
            "password_hash": generate_password_hash(password, method=DEFAULT_HASH_METHOD),
            "is_verified": False,
            "verification_token": verification_token,
            "verification_token_expiry": get_token_expiry(),
            "password_reset_token": None,
            "password_reset_token_expiry": None
        }
        save_users(app_instance, users)
        send_verification_email(app_instance, email, username, verification_token)

        flash("Registration almost complete! Please check your email to verify your account.", "info")
        app_instance.logger.info(f"AuthPlugin: User '{username}' registered, pending verification.")
        return redirect(url_for(f"{AUTH_BLUEPRINT_NAME}.login_route"))

    return render_template('register.html', title="Register")

@auth_bp.route('/verify-email/<token>')
def verify_email_route(token):
    app_instance = getattr(g, 'app', current_app._get_current_object())
    users = load_users(app_instance)
    user_to_verify = None
    username_verified = None

    for username, data in users.items():
        if data.get("verification_token") == token:
            user_to_verify = data
            username_verified = username
            break
    
    if user_to_verify:
        expiry_str = user_to_verify.get("verification_token_expiry")
        if expiry_str and datetime.utcnow() < datetime.fromisoformat(expiry_str):
            user_to_verify["is_verified"] = True
            user_to_verify["verification_token"] = None
            user_to_verify["verification_token_expiry"] = None
            save_users(app_instance, users)
            flash("Email verified successfully! You can now log in.", "success")
            app_instance.logger.info(f"AuthPlugin: User '{username_verified}' email verified.")
        else:
            flash("Verification link has expired or is invalid. Please try registering again or contact support.", "error")
            app_instance.logger.warning(f"AuthPlugin: Expired or invalid verification token used: {token}")
    else:
        flash("Invalid verification token.", "error")
        app_instance.logger.warning(f"AuthPlugin: Invalid verification token presented: {token}")
    
    return redirect(url_for(f"{AUTH_BLUEPRINT_NAME}.login_route"))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login_route():
    app_instance = getattr(g, 'app', current_app._get_current_object())
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            flash("Username and password are required.", "error")
            return render_template('login.html', title="Login")

        users = load_users(app_instance)
        user_data = users.get(username)

        if user_data and check_password_hash(user_data.get("password_hash", ""), password):
            if not user_data.get("is_verified", False):
                flash("Your account is not verified. Please check your email for the verification link.", "warning")
                return render_template('login.html', title="Login", username=username)
            
            session['current_user'] = username 
            flash("Logged in successfully!", "success")
            app_instance.logger.info(f"AuthPlugin: User logged in: {username}")
            next_url = request.args.get('next') or url_for('index') 
            return redirect(next_url)
        else:
            flash("Invalid username or password.", "error")
            return render_template('login.html', title="Login", username=username)

    return render_template('login.html', title="Login")

@auth_bp.route('/logout')
def logout_route():
    app_instance = getattr(g, 'app', current_app._get_current_object())
    username = session.pop('current_user', None)
    if username:
        flash("You have been logged out.", "success")
        app_instance.logger.info(f"AuthPlugin: User logged out: {username}")
    return redirect(url_for('index'))

@auth_bp.route('/request-password-reset', methods=['GET', 'POST'])
def request_password_reset_route():
    app_instance = getattr(g, 'app', current_app._get_current_object())
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        if not email:
            flash("Email address is required.", "error")
            return render_template('request_password_reset.html', title="Request Password Reset")

        users = load_users(app_instance)
        user_found = None
        username_for_reset = None
        for username, data in users.items():
            if data.get('email') == email and data.get('is_verified'): # Only for verified users
                user_found = data
                username_for_reset = username
                break
        
        if user_found:
            reset_token = generate_token()
            user_found["password_reset_token"] = reset_token
            user_found["password_reset_token_expiry"] = get_token_expiry()
            save_users(app_instance, users)
            send_password_reset_email(app_instance, email, username_for_reset, reset_token)
            flash("If an account with that email exists, a password reset link has been sent.", "info")
            app_instance.logger.info(f"AuthPlugin: Password reset requested for email {email} (User: {username_for_reset}).")
        else:
            # Show generic message to avoid confirming if an email/user exists
            flash("If an account with that email exists, a password reset link has been sent.", "info")
            app_instance.logger.warning(f"AuthPlugin: Password reset requested for non-existent or unverified email: {email}")
        
        return redirect(url_for(f"{AUTH_BLUEPRINT_NAME}.login_route"))

    return render_template('request_password_reset.html', title="Request Password Reset")

@auth_bp.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password_with_token_route(token):
    app_instance = getattr(g, 'app', current_app._get_current_object())
    users = load_users(app_instance)
    user_to_reset = None
    username_for_reset = None

    for username, data in users.items():
        if data.get("password_reset_token") == token:
            user_to_reset = data
            username_for_reset = username
            break
    
    if not user_to_reset:
        flash("Invalid or expired password reset token.", "error")
        return redirect(url_for(f"{AUTH_BLUEPRINT_NAME}.login_route"))

    expiry_str = user_to_reset.get("password_reset_token_expiry")
    if not expiry_str or datetime.utcnow() > datetime.fromisoformat(expiry_str):
        # Clear expired token
        user_to_reset["password_reset_token"] = None
        user_to_reset["password_reset_token_expiry"] = None
        save_users(app_instance, users)
        flash("Password reset link has expired. Please request a new one.", "error")
        return redirect(url_for(f"{AUTH_BLUEPRINT_NAME}.login_route"))

    if request.method == 'POST':
        new_password = request.form.get('new_password')
        confirm_password = request.form.get('confirm_password')

        if not new_password or not confirm_password:
            flash("Both password fields are required.", "error")
            return render_template('reset_password_form.html', title="Reset Password", token=token)
        if new_password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template('reset_password_form.html', title="Reset Password", token=token)
        if not check_password(new_password):
            flash("Password must contain at least one uppercase letter and one numeral and be at least 8 characters long.", "error")
            return render_template('reset_password_form.html', title="Reset Password", token=token)

        user_to_reset["password_hash"] = generate_password_hash(new_password, method=DEFAULT_HASH_METHOD)
        user_to_reset["password_reset_token"] = None
        user_to_reset["password_reset_token_expiry"] = None
        save_users(app_instance, users)
        
        flash("Your password has been reset successfully. Please log in.", "success")
        app_instance.logger.info(f"AuthPlugin: Password reset successful for user '{username_for_reset}'.")
        return redirect(url_for(f"{AUTH_BLUEPRINT_NAME}.login_route"))

    return render_template('reset_password_form.html', title="Reset Password", token=token)


# --- Helper to make app instance available to blueprint routes via g ---
def before_request_handler(app_instance):
    def handler():
        g.app = app_instance
    return handler

# --- Current User & Template Context ---
def get_current_user_from_session():
    return session.get('current_user')

def inject_user_to_templates():
    return dict(current_user=get_current_user_from_session())


# --- Plugin Registration Function ---
def register(app_instance, register_hook_func):
    auth_bp.before_request(before_request_handler(app_instance))
    app_instance.register_blueprint(auth_bp, url_prefix='/auth')
    app_instance.context_processor(inject_user_to_templates)

    users_file = get_users_file_path(app_instance)
    if not os.path.exists(users_file):
        app_instance.logger.info(f"AuthPlugin: Users file not found at {users_file}. Creating empty users file.")
        save_users(app_instance, {}) 

    app_instance.logger.info("Enhanced Authentication plugin registered with routes at /auth.")
