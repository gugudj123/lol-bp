import eventlet
eventlet.monkey_patch()
from flask import Flask, render_template_string, request
from flask_socketio import SocketIO, emit

app = Flask(__name__)
app.config['SECRET_KEY'] = 'lol_bp_secret!'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

# 简化的 BP 顺序 (排位征召模式: 6 Ban, 6 Pick, 4 Ban, 4 Pick)
SEQUENCE = [
    {'team': 'blue', 'type': 'ban', 'index': 0}, {'team': 'red', 'type': 'ban', 'index': 0},
    {'team': 'blue', 'type': 'ban', 'index': 1}, {'team': 'red', 'type': 'ban', 'index': 1},
    {'team': 'blue', 'type': 'ban', 'index': 2}, {'team': 'red', 'type': 'ban', 'index': 2},
    {'team': 'blue', 'type': 'pick', 'index': 0}, {'team': 'red', 'type': 'pick', 'index': 0}, {'team': 'red', 'type': 'pick', 'index': 1},
    {'team': 'blue', 'type': 'pick', 'index': 1}, {'team': 'blue', 'type': 'pick', 'index': 2}, {'team': 'red', 'type': 'pick', 'index': 2},
    {'team': 'red', 'type': 'ban', 'index': 3}, {'team': 'blue', 'type': 'ban', 'index': 3},
    {'team': 'red', 'type': 'pick', 'index': 3}, {'team': 'blue', 'type': 'pick', 'index': 3},
    {'team': 'red', 'type': 'pick', 'index': 4}, {'team': 'blue', 'type': 'pick', 'index': 4}
]

# 初始化状态
game_state = {
    'step': 0,
    'blue': {'bans': [None]*5, 'picks': [None]*5},
    'red': {'bans': [None]*5, 'picks': [None]*5}
}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>LOL 双端实时 BP</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
    <style>
        body { background-color: #111; color: white; font-family: sans-serif; margin: 0; padding: 20px; display: flex; flex-direction: column; align-items: center; }
        h1 { color: #f0c340; text-shadow: 0 0 10px #f0c340; }
        .status-bar { font-size: 24px; font-weight: bold; margin-bottom: 20px; padding: 10px 30px; border-radius: 8px; background: #222; }
        .container { display: flex; width: 100%; max-width: 1200px; justify-content: space-between; gap: 20px; }
        .team { width: 30%; background: #1e1e1e; padding: 15px; border-radius: 10px; display: flex; flex-direction: column; align-items: center; }
        .blue-team { border-top: 5px solid #3498db; }
        .red-team { border-top: 5px solid #e74c3c; }
        .grid { display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; margin-bottom: 15px; }
        .slot { width: 60px; height: 60px; background: #333; border-radius: 5px; border: 2px solid transparent; display: flex; justify-content: center; align-items: center; overflow: hidden; position: relative; }
        .slot img { width: 100%; height: 100%; object-fit: cover; }
        .slot.ban img { filter: grayscale(100%) brightness(50%); }
        .slot.ban::after { content: 'X'; position: absolute; color: red; font-size: 40px; font-weight: bold; }
        .slot.active { border-color: #f0c340; box-shadow: 0 0 15px #f0c340; }
        .hero-list { width: 35%; background: #1e1e1e; padding: 10px; border-radius: 10px; height: 500px; overflow-y: auto; }
        .hero-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(50px, 1fr)); gap: 5px; }
        .hero-item { width: 50px; height: 50px; cursor: pointer; border-radius: 5px; transition: transform 0.1s; }
        .hero-item:hover { transform: scale(1.1); border: 2px solid #f0c340; }
        .hidden { display: none !important; }
    </style>
</head>
<body>
    <h1>LOL 双端实时 BP</h1>
    <div class="status-bar" id="statusText">连接中...</div>
    
    <div class="container">
        <!-- 蓝方 -->
        <div class="team blue-team">
            <h2 style="color:#3498db;">蓝方 (Blue)</h2>
            <h3>Ban</h3>
            <div class="grid" id="blue-bans"></div>
            <h3>Pick</h3>
            <div class="grid" id="blue-picks"></div>
        </div>

        <!-- 英雄池 -->
        <div class="hero-list">
            <h3 style="text-align:center; color:#f0c340;">英雄列表</h3>
            <div class="hero-grid" id="hero-pool"></div>
        </div>

        <!-- 红方 -->
        <div class="team red-team">
            <h2 style="color:#e74c3c;">红方 (Red)</h2>
            <h3>Ban</h3>
            <div class="grid" id="red-bans"></div>
            <h3>Pick</h3>
            <div class="grid" id="red-picks"></div>
        </div>
    </div>

    <script>
        // 获取当前链接对应的阵营 (http://127.0.0.1:5000/?side=blue)
        const urlParams = new URLSearchParams(window.location.search);
        const mySide = urlParams.get('side') || 'spectator';
        const socket = io();

        // 英雄头像的基础 URL (使用 Riot 官方 CDN)
        const ddVersion = '14.4.1';
        const imgBase = `https://ddragon.leagueoflegends.com/cdn/${ddVersion}/img/champion/`;
        
        // 获取英雄列表 (简中)
        let heroes = [];
        fetch(`https://ddragon.leagueoflegends.com/cdn/${ddVersion}/data/zh_CN/champion.json`)
            .then(res => res.json())
            .then(data => {
                heroes = Object.values(data.data).map(h => ({
                    id: h.id, // 用于加载图片
                    name: h.name // 中文名
                })).sort((a,b) => a.name.localeCompare(b.name, 'zh-Hans-CN'));
                renderHeroPool();
            });

        function renderHeroPool() {
            const pool = document.getElementById('hero-pool');
            pool.innerHTML = '';
            heroes.forEach(h => {
                const img = document.createElement('img');
                img.src = imgBase + h.id + '.png';
                img.className = 'hero-item';
                img.title = h.name;
                img.onclick = () => submitHero(h.id);
                pool.appendChild(img);
            });
        }

        function submitHero(heroId) {
            if (mySide === 'spectator') { alert("观战模式不能选人哦"); return; }
            socket.emit('submit_hero', {'hero': heroId, 'side': mySide});
        }

        // 收到服务器状态更新
        socket.on('state_update', (data) => {
            updateUI(data);
        });

        function updateUI(state) {
            // 更新状态文字
            const statusEl = document.getElementById('statusText');
            if (state.step >= 18) {
                statusEl.innerText = "BP 已结束！去游戏里盲选吧！";
                statusEl.style.color = "#2ecc71";
                return;
            }
            
            const current = state.current_step;
            const teamName = current.team === 'blue' ? '蓝方' : '红方';
            const typeName = current.type === 'ban' ? 'Ban' : 'Pick';
            
            statusEl.innerText = `当前操作：${teamName} ${typeName} ${current.index + 1}`;
            statusEl.style.color = current.team === 'blue' ? '#3498db' : '#e74c3c';

            // 渲染格子
            ['blue', 'red'].forEach(team => {
                ['ban', 'pick'].forEach(type => {
                    for (let i = 0; i < 5; i++) {
                        const el = document.getElementById(`${team}-${type}-${i}`);
                        const val = state[team][type + 's'][i];
                        el.innerHTML = '';
                        el.className = 'slot';
                        
                        if (val) {
                            const img = document.createElement('img');
                            img.src = imgBase + val + '.png';
                            el.appendChild(img);
                            if (type === 'ban') el.classList.add('ban');
                        } else if (state.step < 18 && current.team === team && current.type === type && current.index === i) {
                            el.classList.add('active'); // 高亮当前需要操作的格子
                        }
                    }
                });
            });
        }

        // 初始化网格
        ['blue-bans', 'blue-picks', 'red-bans', 'red-picks'].forEach(id => {
            const container = document.getElementById(id);
            for(let i=0; i<5; i++) {
                const slot = document.createElement('div');
                slot.className = 'slot';
                slot.id = id.split('-')[0] + '-' + id.split('-')[1] + '-' + i; // 例如 blue-bans-0
                container.appendChild(slot);
            }
        });
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@socketio.on('connect')
def handle_connect():
    emit('state_update', {'current_step': SEQUENCE[game_state['step']] if game_state['step'] < len(SEQUENCE) else None, **game_state}, broadcast=True)

@socketio.on('submit_hero')
def handle_submit(data):
    hero = data['hero']
    side = data['side']
    
    step = game_state['step']
    if step >= len(SEQUENCE): return
    
    current_step = SEQUENCE[step]
    
    # 验证是否是当前操作方的回合
    if current_step['team'] != side:
        return # 不是你的回合，忽略
        
    # 检查该英雄是否已经被 Ban 或 Pick 过了
    for t in ['blue', 'red']:
        if hero in game_state[t]['bans'] or hero in game_state[t]['picks']:
            return # 已经选过了
            
    # 记录操作
    type_str = current_step['type'] + 's'
    game_state[current_step['team']][type_str][current_step['index']] = hero
    game_state['step'] += 1
    
    # 广播新状态给两端
    next_step = SEQUENCE[game_state['step']] if game_state['step'] < len(SEQUENCE) else None
    socketio.emit('state_update', {'current_step': next_step, **game_state})

if __name__ == '__main__':
    print("="*50)
    print("BP服务器已启动！")
    print("1. 蓝方队长请用浏览器打开：http://127.0.0.1:5000/?side=blue")
    print("2. 红方队长请用浏览器打开：http://127.0.0.1:5000/?side=red")
    print("3. 如果想在同一个电脑测试，开两个无痕窗口分别粘贴上面的地址。")
    print("4. 如果想在局域网测试，把 127.0.0.1 换成本机的局域网 IP（如 192.168.x.x）")
    print("="*50)
    # 原来的 socketio.run 不要用了
# if __name__ == '__main__':
#     socketio.run(app, host='0.0.0.0', port=5000, debug=False)

# 新增以下代码
from gevent import pywsgi
from geventwebsocket.handler import WebSocketHandler

if __name__ == '__main__':
    server = pywsgi.WSGIServer(('0.0.0.0', 5000), app, handler_class=WebSocketHandler)
    server.serve_forever()