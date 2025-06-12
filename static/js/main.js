// Socket setup
const socket = io();
let isLeader = false;
let syncEnabled = true;

// Markdown setup
function initMarkdownChords() {
    const md = window.markdownit();
    md.inline.ruler.before('emphasis', 'chord', function(state, silent) {
        let pos = state.pos;
        if (state.src.charCodeAt(pos) !== 0x5B) return false; // [
        
        let match = state.src.slice(pos).match(/^\[(.*?)\]/);
        if (!match) return false;
        
        if (!silent) {
            state.push('chord_open', 'span', 1);
            state.push('text', '', 0).content = match[1];
            state.push('chord_close', 'span', -1);
        }
        
        state.pos += match[0].length;
        return true;
    });
    return md;
}

// Socket functions
function joinRoom(roomCode) {
    socket.emit('join', {room: roomCode});
}

function toggleLeadership() {
    isLeader = !isLeader;
    document.getElementById('leaderStatus').textContent = 
        isLeader ? 'Leading' : 'Following';
}

function toggleSync() {
    syncEnabled = !syncEnabled;
    document.getElementById('syncStatus').textContent = 
        syncEnabled ? 'Sync On' : 'Sync Off';
}

// Scroll handling
const lyricContainer = document.querySelector('.lyrics-container');
if (lyricContainer) {
    lyricContainer.addEventListener('scroll', debounce(() => {
        if (isLeader && syncEnabled) {
            socket.emit('scroll_position', {
                room: roomCode,
                position: lyricContainer.scrollTop
            });
        }
    }, 100));
}

socket.on('update_scroll', (position) => {
    if (!isLeader && syncEnabled && lyricContainer) {
        lyricContainer.scrollTop = position;
    }
});

function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}