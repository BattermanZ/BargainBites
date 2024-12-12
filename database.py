import sqlite3
import json
import threading

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

    def close(self):
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
            self._local.cursor = None

