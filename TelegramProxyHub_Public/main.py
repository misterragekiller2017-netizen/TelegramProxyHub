import csv, os, re, socket, sqlite3, sys, time, urllib.parse, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import Request, urlopen
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QApplication, QFileDialog, QHeaderView, QLabel, QMainWindow,
    QMessageBox, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QHBoxLayout,
    QWidget, QAbstractItemView)

APP_NAME = "Telegram Proxy Hub"
APP_DIR = os.path.join(os.getenv("APPDATA", os.path.expanduser("~")), "TelegramProxyHub")
os.makedirs(APP_DIR, exist_ok=True)
DB_PATH = os.path.join(APP_DIR, "proxies.sqlite3")
SOURCES = [
    ("MTProto", "https://raw.githubusercontent.com/iwizard7/MTProxy_list/data/working.txt"),
    ("MTProto", "https://raw.githubusercontent.com/iwizard7/MTProxy_list/data/all.txt"),
    ("MTProto", "https://raw.githubusercontent.com/tgmtproxy/telegram-mtproto-proxy-list/main/proxies.txt"),
    ("SOCKS5", "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/socks5.txt"),
]
MAX_FEED_BYTES, FETCH_TIMEOUT, PROBE_TIMEOUT, MAX_WORKERS = 8*1024*1024, 15, 3.5, 64

class Signals(QObject):
    message = Signal(str)
    finished = Signal(str)
    refreshed = Signal()

def connect_db():
    con = sqlite3.connect(DB_PATH, timeout=20)
    con.execute("""CREATE TABLE IF NOT EXISTS proxies (
        id INTEGER PRIMARY KEY, protocol TEXT NOT NULL, host TEXT NOT NULL, port INTEGER NOT NULL,
        secret TEXT NOT NULL DEFAULT '', username TEXT NOT NULL DEFAULT '', password TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'TCP доступен', latency_ms INTEGER, checked_at INTEGER NOT NULL DEFAULT 0,
        UNIQUE(protocol,host,port,secret,username,password))""")
    con.execute("DELETE FROM proxies WHERE protocol='MTProto' AND (secret='' OR port<1 OR port>65535)")
    con.commit()
    return con

def valid_host(host):
    if not host or len(host)>253 or any(c.isspace() for c in host): return False
    host = host.strip("[]")
    for family in (socket.AF_INET, socket.AF_INET6):
        try: socket.inet_pton(family, host); return True
        except OSError: pass
    return bool(re.fullmatch(r"(?=.{1,253}$)([A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)*[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", host))

def parse_entry(line, default_protocol, source):
    line = line.strip().strip('"').strip("'")
    if not line or line.startswith("#"): return None
    try:
        if line.startswith(("tg://proxy?", "https://t.me/proxy?")):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(line).query)
            host, port, secret = q.get("server", [""])[0], int(q.get("port", ["0"])[0]), q.get("secret", [""])[0]
            if valid_host(host) and 1<=port<=65535 and secret:
                return ("MTProto", host, port, secret, "", "", source)
        if line.lower().startswith(("socks5://", "socks4://", "socks://")):
            u = urllib.parse.urlparse(line); host, port = u.hostname, u.port
            if host and port and valid_host(host) and 1<=port<=65535:
                return ("SOCKS5", host, port, "", urllib.parse.unquote(u.username or ""), urllib.parse.unquote(u.password or ""), source)
        if default_protocol == "SOCKS5":
            m = re.fullmatch(r"(\[[0-9a-fA-F:]+\]|[^:\s]+):(\d{1,5})", line)
            if m:
                host, port = m.group(1).strip("[]"), int(m.group(2))
                if valid_host(host) and 1<=port<=65535:
                    return ("SOCKS5", host, port, "", "", "", source)
    except (ValueError, TypeError): return None
    return None

def fetch_source(protocol, url):
    req = Request(url, headers={"User-Agent":"TelegramProxyHub/1.0"})
    with urlopen(req, timeout=FETCH_TIMEOUT) as r: raw = r.read(MAX_FEED_BYTES).decode("utf-8","ignore")
    found=[]
    for line in raw.splitlines():
        item=parse_entry(line, protocol, url)
        if item: found.append(item)
    return found

def probe_tcp(item):
    _, host, port, *_ = item
    started=time.monotonic()
    try:
        with socket.create_connection((host,port),timeout=PROBE_TIMEOUT): return True,int((time.monotonic()-started)*1000)
    except OSError: return False,None

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__(); self.setWindowTitle(APP_NAME); self.resize(1000,600); self.setMinimumSize(760,440)
        self.signals=Signals(); self.signals.message.connect(self.statusBar().showMessage)
        self.signals.finished.connect(self.on_finished); self.signals.refreshed.connect(self.load_rows)
        root=QWidget(); self.setCentralWidget(root); layout=QVBoxLayout(root)
        layout.setContentsMargins(16,14,16,14); layout.setSpacing(10)
        head=QHBoxLayout(); title=QLabel("TELEGRAM PROXY HUB"); title.setStyleSheet("font-size:20px;font-weight:700")
        self.count=QLabel("0 рабочих прокси"); self.count.setStyleSheet("color:#27965b")
        head.addWidget(title); head.addStretch(); head.addWidget(self.count); layout.addLayout(head)
        actions=QHBoxLayout()
        self.collect=QPushButton("Собрать прокси"); self.check=QPushButton("Проверить ещё раз"); self.copy=QPushButton("Копировать выбранный")
        for b in (self.collect,self.check,self.copy): b.setMinimumHeight(38); actions.addWidget(b)
        layout.addLayout(actions)
        self.table=QTableWidget(0,6); self.table.setHorizontalHeaderLabels(["Тип","IP / Host","Порт","Secret / логин","Статус","Пинг"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows); self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers); self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False); self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True); layout.addWidget(self.table)
        note=QLabel("Нерабочие записи удаляются автоматически. TCP-проверка не гарантирует полноценную работу или безопасность прокси.")
        note.setWordWrap(True); note.setStyleSheet("color:#777;font-size:11px"); layout.addWidget(note)
        self.collect.clicked.connect(self.collect_and_check); self.check.clicked.connect(self.check_existing); self.copy.clicked.connect(self.copy_selected)
        menu=self.menuBar().addMenu("Файл"); act=QAction("Экспорт рабочего списка CSV…",self); act.triggered.connect(self.export_csv); menu.addAction(act)
        self.load_rows()

    def load_rows(self):
        con=connect_db(); rows=con.execute("SELECT id,protocol,host,port,secret,username,status,latency_ms FROM proxies ORDER BY protocol,host,port").fetchall(); con.close()
        self.table.setRowCount(len(rows))
        for i,(proxy_id,proto,host,port,secret,user,status,lat) in enumerate(rows):
            vals=[proto,host,str(port),secret or user or "—",status or "TCP доступен",f"{lat} ms" if lat is not None else "—"]
            for j,v in enumerate(vals): self.table.setItem(i,j,QTableWidgetItem(str(v)))
            self.table.item(i, 0).setData(32, proxy_id)
        self.count.setText(f"{len(rows)} рабочих прокси")

    def busy(self, yes):
        for b in (self.collect,self.check,self.copy): b.setEnabled(not yes)

    def validate(self, con, rows):
        removed=0
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            jobs={pool.submit(probe_tcp,r[1:]):r[0] for r in rows}
            for f in as_completed(jobs):
                try: alive,lat=f.result()
                except Exception: alive,lat=False,None
                if alive: con.execute("UPDATE proxies SET status='TCP доступен',latency_ms=?,checked_at=? WHERE id=?",(lat,int(time.time()),jobs[f]))
                else: con.execute("DELETE FROM proxies WHERE id=?",(jobs[f],)); removed+=1
        con.commit(); return removed

    def collect_and_check(self):
        self.busy(True); self.signals.message.emit("Собираю открытые списки и проверяю порты…")
        def work():
            entries=[]; failed=0
            with ThreadPoolExecutor(max_workers=len(SOURCES)) as pool:
                futures=[pool.submit(fetch_source,p,u) for p,u in SOURCES]
                for f in as_completed(futures):
                    try: entries.extend(f.result())
                    except Exception: failed+=1
            con=connect_db(); before=con.total_changes
            for e in entries:
                con.execute("INSERT OR IGNORE INTO proxies(protocol,host,port,secret,username,password,source) VALUES(?,?,?,?,?,?,?)",e)
            added=con.total_changes-before; con.commit()
            rows=con.execute("SELECT id,protocol,host,port,secret,username,password,source FROM proxies").fetchall()
            removed=self.validate(con,rows); con.close(); self.signals.refreshed.emit()
            self.signals.finished.emit(f"Готово. Получено записей: {len(entries)}; новых: {added}; удалено нерабочих: {removed}; источников с ошибкой: {failed}.")
        threading.Thread(target=work,daemon=True).start()

    def check_existing(self):
        con=connect_db(); rows=con.execute("SELECT id,protocol,host,port,secret,username,password,source FROM proxies").fetchall(); con.close()
        if not rows: QMessageBox.information(self,APP_NAME,"Список пуст. Сначала нажми «Собрать прокси»."); return
        self.busy(True); self.signals.message.emit("Проверяю прокси; недоступные будут удалены…")
        def work():
            c=connect_db(); rs=c.execute("SELECT id,protocol,host,port,secret,username,password,source FROM proxies").fetchall()
            removed=self.validate(c,rs); c.close(); self.signals.refreshed.emit()
            self.signals.finished.emit(f"Проверка завершена. Удалено недоступных прокси: {removed}.")
        threading.Thread(target=work,daemon=True).start()

    def on_finished(self,msg):
        self.busy(False); self.statusBar().showMessage(msg,15000); QMessageBox.information(self,APP_NAME,msg)

    def copy_selected(self):
        row=self.table.currentRow()
        if row<0: QMessageBox.information(self,APP_NAME,"Сначала выбери прокси в списке."); return
        proto,host,port=[self.table.item(row,i).text() for i in range(3)]
        con=connect_db(); rec=con.execute("SELECT secret,username,password FROM proxies WHERE id=?",(self.table.item(row, 0).data(32),)).fetchone(); con.close()
        if not rec: return
        secret,user,pw=rec
        if proto=="MTProto":
            value=f"tg://proxy?server={urllib.parse.quote(host,safe='')}&port={port}&secret={urllib.parse.quote(secret,safe='')}"
        else:
            auth=(urllib.parse.quote(user,safe='')+":"+urllib.parse.quote(pw,safe='')+"@") if user or pw else ""
            value=f"socks5://{auth}{host}:{port}"
        QApplication.clipboard().setText(value); self.statusBar().showMessage("Прокси скопирован вместе с портом.",4000)

    def export_csv(self):
        path,_=QFileDialog.getSaveFileName(self,"Экспорт рабочего списка","telegram_proxies.csv","CSV (*.csv)")
        if not path:return
        con=connect_db(); rows=con.execute("SELECT protocol,host,port,secret,username,password,latency_ms FROM proxies ORDER BY protocol,host,port").fetchall(); con.close()
        with open(path,"w",newline="",encoding="utf-8-sig") as f:
            w=csv.writer(f); w.writerow(["type","host","port","secret","username","password","latency_ms"]); w.writerows(rows)
        self.statusBar().showMessage("Список экспортирован.",4000)

def main():
    app=QApplication(sys.argv); app.setStyle("Fusion"); window=MainWindow(); window.show(); sys.exit(app.exec())

if __name__=="__main__": main()
