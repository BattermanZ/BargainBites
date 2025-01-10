import sqlite3
import json
import threading
import secrets
import string

class Database:
    _local = threading.local()

    def __init__(self, db_file):
        self.db_file = db_file
        self._connect()

    def _connect(self):
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(self.db_file)
            self._local.cursor = self._local.conn.cursor()
        self.create_tables()

    def create_tables(self):
        self._local.cursor.execute('''
        CREATE TABLE IF NOT EXISTS users_login_data
        (user_id TEXT PRIMARY KEY, credentials TEXT)
        ''')
        self._local.cursor.execute('''
        CREATE TABLE IF NOT EXISTS users_settings_data
        (user_id TEXT PRIMARY KEY, settings TEXT)
        ''')
        self._local.cursor.execute('''
        CREATE TABLE IF NOT EXISTS available_items_favorites
        (item_id TEXT PRIMARY KEY, item_data TEXT)
        ''')
        self._local.cursor.execute('''
        CREATE TABLE IF NOT EXISTS blacklisted_stores
        (user_id TEXT, store_id TEXT, store_name TEXT,
        PRIMARY KEY (user_id, store_id))
        ''')
        self._local.cursor.execute('''
        CREATE TABLE IF NOT EXISTS private_access
        (token TEXT PRIMARY KEY, user_id TEXT UNIQUE, first_name TEXT)
        ''')
        self._local.cursor.execute('''
CREATE TABLE IF NOT EXISTS admin_users
(user_id TEXT PRIMARY KEY)
''')
        self._local.conn.commit()

    def get_users_login_data(self):
        self._connect()
        self._local.cursor.execute('SELECT * FROM users_login_data')
        return {row[0]: json.loads(row[1]) for row in self._local.cursor.fetchall()}

    def save_users_login_data(self, data):
        self._connect()
        for user_id, credentials in data.items():
            self._local.cursor.execute('INSERT OR REPLACE INTO users_login_data VALUES (?, ?)',
                                (user_id, json.dumps(credentials)))
        self._local.conn.commit()

    def get_users_settings_data(self):
        self._connect()
        self._local.cursor.execute('SELECT * FROM users_settings_data')
        return {row[0]: json.loads(row[1]) for row in self._local.cursor.fetchall()}

    def save_users_settings_data(self, data):
        self._connect()
        for user_id, settings in data.items():
            self._local.cursor.execute('INSERT OR REPLACE INTO users_settings_data VALUES (?, ?)',
                                (user_id, json.dumps(settings)))
        self._local.conn.commit()

    def get_available_items_favorites(self):
        self._connect()
        self._local.cursor.execute('SELECT * FROM available_items_favorites')
        return {row[0]: json.loads(row[1]) for row in self._local.cursor.fetchall()}

    def save_available_items_favorites(self, data):
        self._connect()
        for item_id, item_data in data.items():
            self._local.cursor.execute('INSERT OR REPLACE INTO available_items_favorites VALUES (?, ?)',
                                (item_id, json.dumps(item_data)))
        self._local.conn.commit()

    def add_blacklisted_store(self, user_id, store_id, store_name):
        self._connect()
        self._local.cursor.execute('INSERT OR REPLACE INTO blacklisted_stores VALUES (?, ?, ?)',
                            (user_id, store_id, store_name))
        self._local.conn.commit()

    def remove_blacklisted_store(self, user_id, store_id):
        self._connect()
        self._local.cursor.execute('DELETE FROM blacklisted_stores WHERE user_id = ? AND store_id = ?',
                            (user_id, store_id))
        self._local.conn.commit()

    def get_blacklisted_stores(self, user_id):
        self._connect()
        self._local.cursor.execute('SELECT store_id, store_name FROM blacklisted_stores WHERE user_id = ?', (user_id,))
        return self._local.cursor.fetchall()

    def is_store_blacklisted(self, user_id, store_id):
        self._connect()
        self._local.cursor.execute('SELECT 1 FROM blacklisted_stores WHERE user_id = ? AND store_id = ?',
                            (user_id, store_id))
        return bool(self._local.cursor.fetchone())

    def add_user(self, telegram_user_id, credentials):
        self._connect()
        self._local.cursor.execute('INSERT OR REPLACE INTO users_login_data VALUES (?, ?)',
                            (telegram_user_id, json.dumps(credentials)))
        self._local.conn.commit()

    def add_user_settings(self, telegram_user_id, settings):
        self._connect()
        self._local.cursor.execute('INSERT OR REPLACE INTO users_settings_data VALUES (?, ?)',
                            (telegram_user_id, json.dumps(settings)))
        self._local.conn.commit()

    def find_credentials_by_telegramUserID(self, user_id):
        self._connect()
        self._local.cursor.execute('SELECT credentials FROM users_login_data WHERE user_id = ?', (user_id,))
        result = self._local.cursor.fetchone()
        return json.loads(result[0]) if result else None

    def get_user_settings(self, user_id):
        self._connect()
        self._local.cursor.execute('SELECT settings FROM users_settings_data WHERE user_id = ?', (user_id,))
        result = self._local.cursor.fetchone()
        return json.loads(result[0]) if result else None

    def generate_token(self):
        alphabet = string.ascii_letters + string.digits
        token = ''.join(secrets.choice(alphabet) for _ in range(32))
        self._connect()
        self._local.cursor.execute('INSERT INTO private_access (token) VALUES (?)', (token,))
        self._local.conn.commit()
        return token

    def validate_token(self, token):
        self._connect()
        self._local.cursor.execute('SELECT 1 FROM private_access WHERE token = ?', (token,))
        return bool(self._local.cursor.fetchone())

    def authorize_user(self, token, user_id, first_name):
        self._connect()
        self._local.cursor.execute('UPDATE private_access SET user_id = ?, first_name = ? WHERE token = ?', (user_id, first_name, token))
        self._local.conn.commit()
        return self._local.cursor.rowcount > 0

    def is_user_authorized(self, user_id):
        self._connect()
        self._local.cursor.execute('SELECT 1 FROM private_access WHERE user_id = ?', (user_id,))
        return bool(self._local.cursor.fetchone())

    def get_all_tokens(self):
        self._connect()
        self._local.cursor.execute('SELECT token, user_id, first_name FROM private_access')
        return self._local.cursor.fetchall()

    def close(self):
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
            self._local.cursor = None

    def is_admin(self, user_id):
        self._connect()
        user_id_str = str(user_id)
        self._local.cursor.execute('SELECT 1 FROM admin_users WHERE user_id = ?', (user_id_str,))
        result = bool(self._local.cursor.fetchone())
        print(f"Database admin check for user {user_id_str}: {result}")  # Add this line for debugging
        return result

