from flask import Flask, render_template, redirect, url_for, request, jsonify, abort
from flask_socketio import SocketIO, emit, join_room
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_required, current_user, login_user, logout_user
from werkzeug.security import generate_password_hash, check_password_hash
import os

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///songs.db'
db = SQLAlchemy(app)
socketio = SocketIO(app, cors_allowed_origins="*")

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# MODELI
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

class GlobalState(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    current_song_id = db.Column(db.Integer, db.ForeignKey('song.id'))

@login_manager.user_loader
def load_user(id):
    return User.query.get(int(id))

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    init_db()
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['username']).first()
        if user and user.check_password(request.form['password']):
            login_user(user)
            return redirect(url_for('songs'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

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
        lyrics = request.form['lyrics'].replace('\r\n', '\n')
        song = Song(title=request.form['title'], lyrics=lyrics, user_id=current_user.id)
        db.session.add(song)
        db.session.commit()
        return redirect(url_for('songs'))
    return render_template('editor.html')


@app.route('/edit_song/<int:song_id>', methods=['GET', 'POST'])
@login_required
def edit_song(song_id):
    song = Song.query.get_or_404(song_id)
    if current_user.username != 'zigazore':
        abort(403)
    if request.method == 'POST':
        song.title = request.form['title']
        song.lyrics = request.form['lyrics'].replace('\r\n', '\n')
        db.session.commit()
        return redirect(url_for('songs'))
    return render_template('edit_song.html', song=song)

@app.route('/delete_song/<int:song_id>', methods=['POST'])
@login_required
def delete_song(song_id):
    song = Song.query.get_or_404(song_id)
    if current_user.username != 'zigazore':
        abort(403)
    db.session.delete(song)
    db.session.commit()
    return redirect(url_for('songs'))

@app.route('/select_song', methods=['POST'])
@login_required
def select_song():
    song_id = request.form['song_id']
    song = Song.query.get_or_404(song_id)
    global_state = GlobalState.query.first()
    if not global_state:
        global_state = GlobalState(current_song_id=song.id)
        db.session.add(global_state)
    else:
        global_state.current_song_id = song.id
    db.session.commit()
    socketio.emit('room_song_updated', {'song_id': song.id, 'title': song.title, 'lyrics': song.lyrics}, room='GLOBAL')
    return redirect(url_for('room'))

@app.route('/room')
@login_required
def room():
    global_state = GlobalState.query.first()
    song = Song.query.get(global_state.current_song_id) if global_state else None
    songs = [{ 'id': s.id, 'title': s.title, 'lyrics': s.lyrics } for s in Song.query.all()]
    return render_template('room.html', current_song=song, song=song, songs=songs, public=False)

@socketio.on('join')
def on_join(data):
    join_room("GLOBAL")
    print(f"Client joined GLOBAL room")
    global_state = GlobalState.query.first()
    if global_state and global_state.current_song_id:
        song = Song.query.get(global_state.current_song_id)
        emit('room_song_updated', {'song_id': song.id, 'title': song.title, 'lyrics': song.lyrics})

@socketio.on('change_room_song')
def handle_room_song_change(data):
    global_state = GlobalState.query.first()
    if global_state:
        global_state.current_song_id = data['song_id']
    else:
        global_state = GlobalState(current_song_id=data['song_id'])
        db.session.add(global_state)
    db.session.commit()
    emit('room_song_updated', data, room='GLOBAL', broadcast=True)

@socketio.on('lyrics_changed')
def handle_lyrics_update(data):
    emit('update_lyrics', {'lyrics': data['lyrics']}, room='GLOBAL', broadcast=True)

@socketio.on('scroll_position')
def handle_scroll(data):
    emit('update_scroll', data['position'], room='GLOBAL', broadcast=True, include_self=False)

@socketio.on('connect')
def test_connect():
    print('Client connected')

@socketio.on('disconnect')
def test_disconnect():
    print('Client disconnected')

def init_db():
    with app.app_context():
        db.create_all()
        if not GlobalState.query.first():
            db.session.add(GlobalState(current_song_id=None))
            db.session.commit()
        user = User.query.filter_by(username='zigazore').first()
        if not user:
            user = User(username='zigazore')
            user.set_password('mojegeslo123')
            db.session.add(user)
            db.session.commit()
        else:
            user.set_password('mojegeslo123')
            db.session.commit()
        print("Database initialized.")

@app.errorhandler(403)
def forbidden(e):
    return render_template("403.html"), 403

if __name__ == '__main__':
    init_db()
    socketio.run(app, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))