import sqlite3
import json

class Database:
    def __init__(self, db_file):
        self.db_file = db_file
        self.conn = sqlite3.connect(db_file, check_same_thread=False)
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users_login_data
        (user_id TEXT PRIMARY KEY, credentials TEXT)
        ''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS users_settings_data
        (user_id TEXT PRIMARY KEY, settings TEXT)
        ''')
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS available_items_favorites
        (item_id TEXT PRIMARY KEY, item_data TEXT)
        ''')
        self.conn.commit()

    def get_users_login_data(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM users_login_data')
        return {row[0]: json.loads(row[1]) for row in cursor.fetchall()}

    def save_users_login_data(self, data):
        cursor = self.conn.cursor()
        for user_id, credentials in data.items():
            cursor.execute('INSERT OR REPLACE INTO users_login_data (user_id, credentials) VALUES (?, ?)',
                           (user_id, json.dumps(credentials)))
        self.conn.commit()

    def get_users_settings_data(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM users_settings_data')
        return {row[0]: json.loads(row[1]) for row in cursor.fetchall()}

    def save_users_settings_data(self, data):
        cursor = self.conn.cursor()
        for user_id, settings in data.items():
            cursor.execute('INSERT OR REPLACE INTO users_settings_data (user_id, settings) VALUES (?, ?)',
                           (user_id, json.dumps(settings)))
        self.conn.commit()

    def get_available_items_favorites(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM available_items_favorites')
        return {row[0]: json.loads(row[1]) for row in cursor.fetchall()}

    def save_available_items_favorites(self, data):
        cursor = self.conn.cursor()
        for item_id, item_data in data.items():
            cursor.execute('INSERT OR REPLACE INTO available_items_favorites (item_id, item_data) VALUES (?, ?)',
                           (item_id, json.dumps(item_data)))
        self.conn.commit()

    def close(self):
        self.conn.close()