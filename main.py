from flask import Flask, render_template, redirect, url_for, request, jsonify, abort
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_required, current_user, login_user, logout_user
from werkzeug.security import generate_password_hash, check_password_hash
import random
import string
import os

# Flask Setup
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///instance/songs.db'
db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")


# Login Manager Setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True)
    password_hash = db.Column(db.String(128))
    songs = db.relationship('Song', backref='author', lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class Song(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100))
    lyrics = db.Column(db.Text)
    likes = db.Column(db.Integer, default=0)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

class Room(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(6), unique=True)
    current_song_id = db.Column(db.Integer, db.ForeignKey('song.id'))

@login_manager.user_loader
def load_user(id):
    return User.query.get(int(id))

# Routes
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.check_password(request.form['password']):
            login_user(user)
            return redirect(url_for('songs'))
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        if User.query.filter_by(username=request.form['username']).first():
            return "Username already exists"
        user = User(username=request.form['username'])
        user.set_password(request.form['password'])
        db.session.add(user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/songs')
@login_required
def songs():
    songs = Song.query.all()
    return render_template('songs.html', songs=songs)

@app.route('/editor', methods=['GET', 'POST'])
@login_required
def editor():
    if request.method == 'POST':
        lyrics = request.form['lyrics'].replace('\r\n', '\n')  # Normalize newlines
        song = Song(
            title=request.form['title'],
            lyrics=lyrics,
            user_id=current_user.id
        )
        db.session.add(song)
        db.session.commit()
        return redirect(url_for('songs'))
    return render_template('editor.html')

@app.route('/edit_song/<int:song_id>', methods=['GET', 'POST'])
@login_required
def edit_song(song_id):
    song = Song.query.get_or_404(song_id)
    
    # Ensure only the author can edit the song
    if song.author != current_user:
        abort(403)  # Forbidden
    
    if request.method == 'POST':
        # Normalize line breaks and preserve formatting
        song.title = request.form['title']
        
        # Preserve both \r\n and \n, convert to \n
        lyrics = request.form['lyrics']
        lyrics = lyrics.replace('\r\n', '\n')
        song.lyrics = lyrics
        
        db.session.commit()
        
        return redirect(url_for('songs'))
    
    return render_template('edit_song.html', song=song)

@app.route('/delete_song/<int:song_id>', methods=['POST'])
@login_required
def delete_song(song_id):
    song = Song.query.get_or_404(song_id)
    
    # Ensure only the author can delete the song
    if song.author != current_user:
        abort(403)  # Forbidden
    
    db.session.delete(song)
    db.session.commit()
    return redirect(url_for('songs'))

@app.route("/select_song", methods=['POST'])
@login_required
def select_song():
    song_id = request.form['song_id']
    
    # Fetch the song again to ensure you have the latest data
    song = Song.query.get_or_404(song_id)
    
    # Create or update the room
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    
    # Try to find an existing room with this song
    room = Room.query.filter_by(current_song_id=song_id).first()
    
    if room:
        # If room exists, use its existing code
        code = room.code
    else:
        # Create a new room
        room = Room(code=code, current_song_id=song.id)
        db.session.add(room)
    
    # Always commit to ensure changes are saved
    db.session.commit()
    
    return redirect(url_for('room', code=room.code))

@app.route('/room/<code>')
@login_required
def room(code):
    room = Room.query.filter_by(code=code).first_or_404()
    song = Song.query.get_or_404(room.current_song_id)
    # Manually serialize songs
    songs = [
        {
            'id': s.id, 
            'title': s.title, 
            'lyrics': s.lyrics
        } for s in Song.query.all()
    ]
    return render_template('room.html', room=room, current_song=song, song=song, songs=songs, public=False)

@app.route('/join/<code>')
def join_room_public(code):
    room = Room.query.filter_by(code=code).first_or_404()
    song = Song.query.get_or_404(room.current_song_id)
    # Manually serialize songs
    songs = [
        {
            'id': s.id, 
            'title': s.title, 
            'lyrics': s.lyrics
        } for s in Song.query.all()
    ]
    return render_template('room.html', room=room, song=song, songs=songs, public=True)

@socketio.on('join')
def on_join(data):
    room = data['room']
    join_room(room)
    print(f"Client joined room: {room}")


@socketio.on('change_room_song')
def handle_room_song_change(data):
    """Handle changing the song for the entire room"""
    room = data['room']
    song_id = data['song_id']
    title = data['title']
    lyrics = data['lyrics']
    
    # Update the room's current song
    room_obj = Room.query.filter_by(code=room).first()
    if room_obj:
        room_obj.current_song_id = song_id
        db.session.commit()
    
    # Broadcast song change to everyone in the room
    emit('room_song_updated', {
        'song_id': song_id, 
        'title': title,
        'lyrics': lyrics
    }, room=room, broadcast=True)

@socketio.on('lyrics_changed')
def handle_lyrics_update(data):
    room = data['room']
    lyrics = data['lyrics']
    print(f"Broadcasting lyrics update to room {room}")
    emit('update_lyrics', {'lyrics': lyrics}, room=room, broadcast=True)

@socketio.on('scroll_position')
def handle_scroll(data):
    room = data['room']
    position = data['position']
    emit('update_scroll', position, room=room, broadcast=True, include_self=False)

@socketio.on('connect')
def test_connect():
    print('Client connected')

@socketio.on('disconnect')
def test_disconnect():
    print('Client disconnected')


def init_db():
    with app.app_context():
        db.create_all()

        # Dodaj začetnega uporabnika, če še ne obstaja
        if not User.query.filter_by(username='zigazore').first():
            user = User(username='zigazore')
            user.set_password('geslo123')  # uporabi svoje geslo
            db.session.add(user)
            db.session.commit()
            print("Testni uporabnik dodan.")
        else:
            print("Uporabnik že obstaja.")

        print("Database initialized!")

if __name__ == '__main__':
    init_db()
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))