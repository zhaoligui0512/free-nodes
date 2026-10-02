#!/usr/bin/env python3
"""
Free Nodes Collector - 免费节点采集、测试、发布工具
支持两种运行模式:
  python3 collector.py --round 1    单轮测试（采集→去重→URL test→保存结果）
  python3 collector.py --finalize   汇总模式（读取所有轮次→计算平均→IP反查→输出）
"""
import yaml, json, base64, urllib.parse, urllib.request, socket, time, subprocess, os, sys, re, argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

WORKDIR = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(WORKDIR, ".cache")

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)

# ============================================================
# 配置加载
# ============================================================
def load_config(path=None):
    if path is None:
        path = os.path.join(WORKDIR, "config.yaml")
    with open(path, "r") as f:
        return yaml.safe_load(f)

# ============================================================
# 订阅源采集
# ============================================================
def fetch_url(url, timeout=30, retries=2):
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as e:
            if attempt < retries:
                log(f"  重试 {attempt+1}/{retries}: {url}")
                time.sleep(2)
            else:
                log(f"  [WARN] 下载失败 {url}: {e}")
                return None
    return None

def fetch_nomorewalls(config):
    url = config["url"]
    log(f"[NoMoreWalls] 下载: {url}")
    data = fetch_url(url)
    if not data:
        log("[NoMoreWalls] 下载失败，返回空")
        return []
    text = data.decode("utf-8", errors="ignore")
    parsed = yaml.safe_load(text)
    proxies = parsed.get("proxies", [])
    log(f"[NoMoreWalls] 获得 {len(proxies)} 个节点")
    return proxies

def fetch_mibei(config):
    homepage_url = config.get("homepage", "https://www.mibei77.com/")
    log(f"[米贝] 抓取首页: {homepage_url}")

    home_html = fetch_url(homepage_url)
    if not home_html:
        log("[米贝] 首页抓取失败")
        return []
    home_text = home_html.decode("utf-8", errors="ignore")

    article_links = re.findall(r'href="(https?://[^"]*?mibei77\.com/\d+\.html)"', home_text)
    if not article_links:
        article_links = re.findall(r'href="(/\d+\.html)"', home_text)
        article_links = ["https://www.mibei77.com" + l for l in article_links]

    if not article_links:
        log("[米贝] 未找到文章链接")
        return []

    article_url = list(dict.fromkeys(article_links))[0]
    log(f"[米贝] 最新文章: {article_url}")

    article_html = fetch_url(article_url)
    if not article_html:
        log("[米贝] 文章页抓取失败")
        return []
    article_text = article_html.decode("utf-8", errors="ignore")

    txt_urls = re.findall(r'(https?://mm\.mibei77\.com/[^"\'\s<>]+\.txt)', article_text)
    yaml_urls = re.findall(r'(https?://mm\.mibei77\.com/[^"\'\s<>]+\.(?:yaml|yml))', article_text)

    proxies = []

    if txt_urls:
        txt_url = txt_urls[0]
        log(f"[米贝] TXT订阅: {txt_url}")
        txt_data = fetch_url(txt_url)
        if txt_data:
            txt_text = txt_data.decode("utf-8", errors="ignore").strip()
            try:
                decoded = base64.b64decode(txt_text).decode("utf-8", errors="ignore")
            except:
                decoded = txt_text
            lines = [l.strip() for l in decoded.split("\n") if l.strip()]
            count = 0
            for line in lines:
                node = parse_node_link(line)
                if node:
                    proxies.append(node)
                    count += 1
            log(f"[米贝] TXT解析: {count} 个节点")
        else:
            log("[米贝] TXT下载失败")

    if yaml_urls:
        yaml_url = yaml_urls[0]
        log(f"[米贝] YAML订阅: {yaml_url}")
        yaml_data = fetch_url(yaml_url)
        if yaml_data:
            yaml_text = yaml_data.decode("utf-8", errors="ignore")
            parsed = yaml.safe_load(yaml_text)
            yaml_proxies = parsed.get("proxies", [])
            log(f"[米贝] YAML解析: {len(yaml_proxies)} 个节点")
            proxies.extend(yaml_proxies)
        else:
            log("[米贝] YAML下载失败")

    log(f"[米贝] 合计: {len(proxies)} 个节点")
    return proxies

def collect_all(config):
    all_proxies = []
    for source in config.get("sources", []):
        stype = source.get("type", "")
        try:
            if stype == "nomorewalls":
                all_proxies.extend(fetch_nomorewalls(source))
            elif stype == "mibei":
                all_proxies.extend(fetch_mibei(source))
            elif stype == "yaml_url":
                data = fetch_url(source["url"])
                if data:
                    parsed = yaml.safe_load(data.decode("utf-8", errors="ignore"))
                    px = parsed.get("proxies", [])
                    log(f"[{source.get('name','yaml')}] 获得 {len(px)} 个节点")
                    all_proxies.extend(px)
        except Exception as e:
            log(f"[ERROR] 源 {source.get('name',stype)} 采集失败: {e}")
    return all_proxies

# ============================================================
# 节点链接解析
# ============================================================
def parse_node_link(link):
    try:
        if link.startswith("vless://"):
            return parse_vless(link)
        elif link.startswith("trojan://"):
            return parse_trojan(link)
        elif link.startswith("ss://"):
            return parse_ss(link)
        elif link.startswith("hysteria2://") or link.startswith("hy2://"):
            return parse_hysteria2(link)
        elif link.startswith("socks5://") or link.startswith("socks://"):
            return parse_socks5(link)
    except Exception as e:
        pass
    return None

def parse_vless(link):
    link = link[len("vless://"):]
    name = "vless_node"
    if "#" in link:
        link, name = link.split("#", 1)
        name = urllib.parse.unquote(name)
    uuid, host_part = link.split("@", 1)
    server, port = host_part, "443"
    if ":" in host_part:
        server, port = host_part.rsplit(":", 1)
    params = {}
    if "?" in port:
        port, query = port.split("?", 1)
        params = dict(urllib.parse.parse_qsl(query))
    node = {"name": name, "type": "vless", "server": server, "port": int(port), "uuid": uuid,
            "network": params.get("type", "tcp")}
    sec = params.get("security", "")
    if sec == "tls":
        node["tls"] = True
        if params.get("sni"): node["servername"] = params["sni"]
        if params.get("fp"): node["client-fingerprint"] = params["fp"]
    elif sec == "reality":
        node["tls"] = True
        node["servername"] = params.get("sni", "")
        node["reality-opts"] = {"public-key": params.get("pbk", ""), "short-id": params.get("sid", "")}
        node["client-fingerprint"] = params.get("fp", "chrome")
    if params.get("path"):
        node["ws-opts"] = {"path": urllib.parse.unquote(params["path"])}
    if params.get("host"):
        node.setdefault("ws-opts", {})["headers"] = {"Host": params["host"]}
    return node

def parse_trojan(link):
    link = link[len("trojan://"):]
    name = "trojan_node"
    if "#" in link:
        link, name = link.split("#", 1)
        name = urllib.parse.unquote(name)
    password, host_part = link.split("@", 1)
    password = urllib.parse.unquote(password)
    server, port = host_part, "443"
    if ":" in host_part:
        server, port = host_part.rsplit(":", 1)
    params = {}
    if "?" in port:
        port, query = port.split("?", 1)
        params = dict(urllib.parse.parse_qsl(query))
    node = {"name": name, "type": "trojan", "server": server, "port": int(port), "password": password}
    if params.get("sni"): node["sni"] = params["sni"]
    if params.get("fp"): node["client-fingerprint"] = params["fp"]
    if params.get("type") == "ws":
        node["network"] = "ws"
        node["ws-opts"] = {"path": params.get("path", "/")}
    return node

def parse_ss(link):
    link = link[len("ss://"):]
    name = "ss_node"
    if "#" in link:
        link, name = link.split("#", 1)
        name = urllib.parse.unquote(name)
    if "@" in link:
        userinfo, host_part = link.rsplit("@", 1)
        try:
            decoded = base64.b64decode(userinfo + "===").decode("utf-8", errors="ignore")
            method, password = decoded.split(":", 1)
        except:
            method, password = "aes-256-gcm", userinfo
    else:
        try:
            decoded = base64.b64decode(link + "===").decode("utf-8", errors="ignore")
            userinfo, host_part = decoded.rsplit("@", 1)
            method, password = userinfo.split(":", 1)
        except:
            return None
    server, port = host_part, "8388"
    if ":" in host_part:
        server, port = host_part.rsplit(":", 1)
    if "?" in port:
        port = port.split("?", 1)[0]
    return {"name": name, "type": "ss", "server": server, "port": int(port),
            "cipher": method, "password": password}

def parse_hysteria2(link):
    if link.startswith("hysteria2://"):
        link = link[len("hysteria2://"):]
    else:
        link = link[len("hy2://"):]
    name = "hy2_node"
    if "#" in link:
        link, name = link.split("#", 1)
        name = urllib.parse.unquote(name)
    password, host_part = link.split("@", 1)
    password = urllib.parse.unquote(password)
    server, port = host_part, "443"
    if ":" in host_part:
        server, port = host_part.rsplit(":", 1)
    params = {}
    if "?" in port:
        port, query = port.split("?", 1)
        params = dict(urllib.parse.parse_qsl(query))
    node = {"name": name, "type": "hysteria2", "server": server, "port": int(port), "password": password}
    if params.get("sni"): node["sni"] = params["sni"]
    if params.get("insecure") == "1": node["skip-cert-verify"] = True
    return node

def parse_socks5(link):
    if link.startswith("socks5://"):
        link = link[len("socks5://"):]
    else:
        link = link[len("socks://"):]
    name = "socks_node"
    if "#" in link:
        link, name = link.split("#", 1)
        name = urllib.parse.unquote(name)
    auth = ""
    if "@" in link:
        auth, host_part = link.split("@", 1)
    else:
        host_part = link
    server, port = host_part, "1080"
    if ":" in host_part:
        server, port = host_part.rsplit(":", 1)
    node = {"name": name, "type": "socks5", "server": server, "port": int(port)}
    if auth and ":" in auth:
        u, p = auth.split(":", 1)
        node["username"] = u
        node["password"] = p
    return node

# ============================================================
# TCP 测活预筛
# ============================================================
TCP_TYPES = {"vless", "trojan", "ss", "shadowsocks", "socks", "socks5", "http", "vmess", "anytls"}
UDP_TYPES = {"hysteria2", "hy2", "wireguard", "tuic"}

def tcp_alive_check(proxies, timeout=5, max_workers=50):
    """TCP 连通性预筛：快速过滤死节点，减轻 URL test 压力。
    - TCP 系协议（vless/trojan/ss/socks/http）：TCP connect 测活
    - UDP 系协议（hysteria2/tuic/wireguard）：TCP 探测会误判，跳过直接保留，
      最终由 URL test 判定真实存活
    """
    targets, skip = [], []
    for p in proxies:
        if p.get("type") in TCP_TYPES:
            targets.append(p)
        else:
            skip.append(p)

    def _check(p):
        try:
            sock = socket.create_connection((p["server"], int(p["port"])), timeout=timeout)
            sock.close()
            return p, True
        except:
            return p, False

    alive, dead = [], []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_check, p): p for p in targets}
        for fut in as_completed(futures):
            p, ok = fut.result()
            if ok:
                alive.append(p)
            else:
                dead.append(p)

    log(f"TCP 测活: TCP协议 {len(targets)} 个 → 存活 {len(alive)}, 死亡 {len(dead)}"
        f"{f', 跳过UDP协议 {len(skip)} 个 (hysteria2等)' if skip else ''}")
    return alive + skip
# Cloudflare IP 段（用于识别 CF 节点，这些节点对中国 IP 通常不可用）
CF_IP_PREFIXES = ("162.159.", "188.114.", "104.16.", "104.17.", "104.18.", "104.19.",
                  "172.64.", "173.245.", "162.35.", "198.41.", "197.234.", "103.21.244.",
                  "103.22.200.", "103.31.4.", "141.101.64.", "108.162.192.", "190.93.240.",
                  "188.114.96.", "188.114.97.", "188.114.98.", "188.114.99.")

def is_cf_server(server):
    """判断 server（域名或IP）是否解析到 Cloudflare IP"""
    try:
        ip = socket.gethostbyname(server)
        return ip.startswith(CF_IP_PREFIXES)
    except:
        return False

def dedup(proxies, max_sni_per_ip=2):
    """去重策略：
    1. 先按 server:port 精确去重
    2. 再按真实 IP 去重：DNS 解析域名→同一真实 IP 最多保留 max_sni_per_ip 个节点
       （同一台服务器挂多个域名/SNI 的只保留前几个）
    保留顺序：先保留精确 server:port 唯一的，再按 IP 截断
    """
    # 第一层：server:port 精确去重
    seen_exact = set()
    unique = []
    for p in proxies:
        key = f"{p.get('server','')}:{p.get('port','')}"
        if key in seen_exact:
            continue
        seen_exact.add(key)
        unique.append(p)

    # 第二层：按真实 IP 去重（同 IP 最多 max_sni_per_ip 个）
    ip_count = {}
    result = []
    for p in unique:
        try:
            ip = socket.gethostbyname(p.get('server',''))
        except:
            ip = p.get('server','')
        cnt = ip_count.get(ip, 0)
        if cnt >= max_sni_per_ip:
            continue
        ip_count[ip] = cnt + 1
        result.append(p)
    return result

# ============================================================
# Mihomo 管理
# ============================================================
def gen_mihomo_config(proxies):
    """从已重命名的节点列表生成mihomo配置（不修改name）"""
    config = {
        "mixed-port": 7890,
        "external-controller": "127.0.0.1:9090",
        "allow-lan": False,
        "mode": "rule",
        "log-level": "error",
        "geodata-mode": True,
        "geo-auto-update": False,
        "proxies": proxies,
        "proxy-groups": [{"name": "PROXY", "type": "select",
                          "proxies": [p["name"] for p in proxies] + ["DIRECT"]}],
        "rules": ["MATCH,PROXY"],
    }
    path = os.path.join(WORKDIR, "mihomo-config.yaml")
    with open(path, "w") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False)
    return proxies

def gen_mihomo_config_from_list(proxies):
    """兼容旧调用，直接用已重命名的列表"""
    return gen_mihomo_config(proxies)

def start_mihomo(config):
    bin_path = config.get("mihomo_bin", os.path.join(WORKDIR, "mihomo"))
    log(f"启动 Mihomo: {bin_path}")
    subprocess.Popen([bin_path, "-d", WORKDIR, "-f", os.path.join(WORKDIR, "mihomo-config.yaml")],
                     stdout=open(os.path.join(WORKDIR, "mihomo.log"), "w"), stderr=subprocess.STDOUT)
    # 等待API就绪，最多重试10次
    for attempt in range(10):
        time.sleep(2)
        try:
            with urllib.request.urlopen("http://127.0.0.1:9090/version", timeout=5) as resp:
                ver = json.loads(resp.read())
                log(f"Mihomo 启动成功: {ver.get('version','unknown')} (尝试{attempt+1}次)")
                return True
        except Exception as e:
            log(f"  等待API就绪... ({attempt+1}/10)")
    log("[ERROR] Mihomo API 不可用，超时")
    return False

def stop_mihomo():
    # 用精确匹配杀mihomo进程，避免pkill -f匹配到脚本自身
    try:
        result = subprocess.run(["pgrep", "-x", "mihomo"], capture_output=True, text=True)
        pids = result.stdout.strip().split()
        for pid in pids:
            subprocess.run(["kill", pid], capture_output=True)
        if pids:
            time.sleep(1)
    except:
        pass
    log("Mihomo 已停止")

# ============================================================
# URL test
# ============================================================
def url_test_one(name, test_urls, timeout):
    """对单个节点测试多个目标 URL，返回 (name, {url: delay})，失败的 delay=0"""
    delays = {}
    for url in test_urls:
        try:
            encoded = urllib.parse.quote(name, safe="")
            req = urllib.request.Request(
                f"http://127.0.0.1:9090/proxies/{encoded}/delay?timeout={timeout*1000}&url={url}",
                method="GET")
            with urllib.request.urlopen(req, timeout=timeout+3) as resp:
                data = json.loads(resp.read())
                delays[url] = data.get("delay", 0)
        except:
            delays[url] = 0
    return name, delays

def batch_url_test(proxies, test_urls, timeout, batch_size=25):
    """批量测试。每个节点必须通过所有 test_urls 才算存活，延迟取所有目标的平均值。"""
    results = {}
    names = [p["name"] for p in proxies]
    total = len(names)
    for i in range(0, total, batch_size):
        batch = names[i:i+batch_size]
        with ThreadPoolExecutor(max_workers=batch_size) as ex:
            futures = {ex.submit(url_test_one, n, test_urls, timeout): n for n in batch}
            for fut in as_completed(futures):
                name, delays = fut.result()
                # 全通才算存活，延迟取平均值
                all_pass = all(d > 0 for d in delays.values())
                if all_pass:
                    results[name] = round(sum(delays.values()) / len(delays))
                else:
                    results[name] = 0
        done = min(i+batch_size, total)
        alive = sum(1 for v in results.values() if v > 0)
        log(f"  进度 {done}/{total}, 存活 {alive}")
    return results

# ============================================================
# IP 反查
# ============================================================
def ip_lookup(server):
    """主库: ipinfo.io（准确度高、免token 5万次/月、无并发限速）
    失败时 fallback 到 ip-api.com"""
    try:
        ip = socket.gethostbyname(server)
    except:
        return server, None
    # 主库 ipinfo.io
    try:
        url = f"https://ipinfo.io/{ip}/json"
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read())
            cc = data.get("country", "")
            if cc:
                # 转成与 ip-api 兼容的结构（country 中文名 + countryCode 两字母码）
                cn_name = {
                    "US": "美国", "JP": "日本", "SG": "新加坡", "TW": "台湾", "KR": "韩国",
                    "HK": "香港", "CN": "中国", "DE": "德国", "GB": "英国", "FR": "法国",
                    "NL": "荷兰", "CA": "加拿大", "AU": "澳大利亚", "RU": "俄罗斯",
                    "RO": "罗马尼亚", "FI": "芬兰", "SE": "瑞典", "CH": "瑞士", "ES": "西班牙",
                    "IT": "意大利", "IN": "印度", "BR": "巴西", "TR": "土耳其", "PL": "波兰",
                    "UA": "乌克兰", "IE": "爱尔兰", "AT": "奥地利", "BE": "比利时",
                    "CZ": "捷克", "DK": "丹麦", "NO": "挪威", "PT": "葡萄牙", "GR": "希腊",
                    "MX": "墨西哥", "TH": "泰国", "VN": "越南", "ID": "印尼", "MY": "马来西亚",
                    "PH": "菲律宾", "NZ": "新西兰", "EG": "埃及", "SA": "沙特", "AE": "阿联酋",
                    "IL": "以色列", "KZ": "哈萨克斯坦", "BG": "保加利亚", "HU": "匈牙利",
                    "SK": "斯洛伐克", "HR": "克罗地亚", "MO": "澳门", "BD": "孟加拉国",
                    "PK": "巴基斯坦", "LK": "斯里兰卡", "KH": "柬埔寨", "NP": "尼泊尔",
                }
                return ip, {
                    "status": "success",
                    "country": cn_name.get(cc, cc),
                    "countryCode": cc,
                    "regionName": data.get("region", ""),
                    "city": data.get("city", ""),
                    "isp": data.get("org", ""),
                    "org": data.get("org", ""),
                    "query": ip,
                }
    except:
        pass
    # fallback: ip-api.com
    try:
        url = f"http://ip-api.com/json/{ip}?lang=zh-CN&fields=status,country,countryCode,regionName,city,isp,org,query"
        with urllib.request.urlopen(url, timeout=8) as resp:
            data = json.loads(resp.read())
            if data.get("status") == "success":
                return ip, data
    except:
        pass
    return ip, None

def batch_ip_lookup(proxies, max_workers=10):
    results = {}
    servers = list(set(p["server"] for p in proxies))
    log(f"IP反查: {len(servers)} 个唯一服务器")
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(ip_lookup, s): s for s in servers}
        for i, fut in enumerate(as_completed(futures)):
            server = futures[fut]
            ip, info = fut.result()
            results[server] = {"ip": ip, "info": info}
            if (i+1) % 20 == 0:
                log(f"  IP查询 {i+1}/{len(servers)}")
    return results

# ============================================================
# 真实名称生成
# ============================================================
COUNTRY_CODE = {
    "United States": "US", "China": "CN", "Japan": "JP", "Singapore": "SG",
    "Hong Kong": "HK", "Taiwan": "TW", "South Korea": "KR", "Germany": "DE",
    "United Kingdom": "GB", "France": "FR", "Netherlands": "NL", "Canada": "CA",
    "Australia": "AU", "Russia": "RU", "Romania": "RO", "Finland": "FI",
    "Sweden": "SE", "Switzerland": "CH", "Spain": "ES", "Italy": "IT",
    "India": "IN", "Brazil": "BR", "Turkey": "TR", "Poland": "PL",
    "Ukraine": "UA", "Iran": "IR", "Ireland": "IE", "Austria": "AT",
    "Belgium": "BE", "Czechia": "CZ", "Denmark": "DK", "Norway": "NO",
    "Portugal": "PT", "Greece": "GR", "Mexico": "MX", "Thailand": "TH",
    "Vietnam": "VN", "Indonesia": "ID", "Malaysia": "MY", "Philippines": "PH",
    "New Zealand": "NZ", "Egypt": "EG", "Saudi Arabia": "SA",
    "United Arab Emirates": "AE", "Israel": "IL", "Kazakhstan": "KZ",
    "Bulgaria": "BG", "Hungary": "HU", "Slovakia": "SK", "Croatia": "HR",
    "Slovenia": "SI", "Estonia": "EE", "Latvia": "LV", "Lithuania": "LT",
    "Iceland": "IS", "Luxembourg": "LU", "Malta": "MT", "Cyprus": "CY",
    "Serbia": "RS", "Moldova": "MD", "Georgia": "GE", "Armenia": "AM",
    "Mongolia": "MN", "Bangladesh": "BD", "Pakistan": "PK", "Sri Lanka": "LK",
    "Cambodia": "KH", "Nepal": "NP", "Russian Federation": "RU",
    "Korea, Republic of": "KR", "South Africa": "ZA", "Nigeria": "NG",
    "Kenya": "KE", "Argentina": "AR", "Chile": "CL", "Colombia": "CO",
    "Peru": "PE", "Bosnia and Herzegovina": "BA", "Azerbaijan": "AZ",
}

ISP_SHORT = ["Cloudflare", "Amazon", "Google", "Microsoft", "DigitalOcean",
             "Vultr", "Linode", "Hetzner", "OVH", "Choopa", "M247",
             "Datacamp", "DataCamp", "Serverion", "HostBrr", "Greencloud",
             "Psychz", "Oracle", "Scaleway", "Hurricane", "PEG", "Baxet",
             "JSC", "Green", "UCLOUD", "Alibaba", "Shenzhen", "Chunghwa", "Fairview"]

def make_real_name(proxy, ip_info, index):
    info = (ip_info or {}).get("info") or {}
    country = info.get("country", "Unknown")
    cc = COUNTRY_CODE.get(country, info.get("countryCode", "XX"))
    city = info.get("city", "")
    isp = info.get("isp", "")
    proto = proxy["type"]

    isp_short = ""
    if isp:
        for kw in ISP_SHORT:
            if kw.lower() in isp.lower():
                isp_short = kw
                break
        if not isp_short:
            isp_short = isp.split()[0] if isp else ""

    parts = [cc]
    if city:
        parts.append(city[:8])
    if isp_short:
        parts.append(isp_short)
    parts.append(proto)
    parts.append(f"{index:02d}")
    return "-".join(parts)

# ============================================================
# 输出格式
# ============================================================
def build_clash_yaml(nodes, output_config):
    proxies = []
    for n in nodes:
        p = dict(n["raw_config"])
        p["name"] = n["real_name"]
        # 清洗：http 节点的 username/password 若为 null/'null'/空则删除
        # （Clash 会把字面 'null' 当作真实认证值导致连接失败）
        for k in ("username", "password"):
            if p.get(k) in (None, "null", ""):
                p.pop(k, None)
        proxies.append(p)

    names = [p["name"] for p in proxies]
    config = {
        "mixed-port": 7890,
        "external-controller": "127.0.0.1:9090",
        "allow-lan": False,
        "mode": "rule",
        "log-level": "info",
        "ipv6": False,
        "proxies": proxies,
        "proxy-groups": [
            {"name": "🚀 节点选择", "type": "select",
             "proxies": ["♻️ 自动选择", "DIRECT"] + names},
            {"name": "♻️ 自动选择", "type": "url-test",
             "proxies": names,
             "url": output_config.get("test_url", "http://www.gstatic.com/generate_204"),
             "interval": 300, "tolerance": 50},
        ],
        "rules": ["MATCH,🚀 节点选择"],
    }
    return config

def node_to_link(p, name):
    ptype = p.get("type", "")
    encoded_name = urllib.parse.quote(name, safe="")

    if ptype == "vless":
        params = {"type": p.get("network", "tcp")}
        if p.get("tls"):
            params["security"] = "tls"
            if p.get("servername"): params["sni"] = p["servername"]
            if p.get("client-fingerprint"): params["fp"] = p["client-fingerprint"]
        if "reality-opts" in p:
            params["security"] = "reality"
            params["pbk"] = p["reality-opts"].get("public-key", "")
            params["sid"] = p["reality-opts"].get("short-id", "")
        if p.get("ws-opts", {}).get("path"):
            params["path"] = p["ws-opts"]["path"]
        if p.get("ws-opts", {}).get("headers", {}).get("Host"):
            params["host"] = p["ws-opts"]["headers"]["Host"]
        qs = urllib.parse.urlencode(params)
        return f"vless://{p['uuid']}@{p['server']}:{p['port']}?{qs}#{encoded_name}"

    elif ptype == "trojan":
        params = {}
        if p.get("sni"): params["sni"] = p["sni"]
        if p.get("client-fingerprint"): params["fp"] = p["client-fingerprint"]
        if p.get("network") == "ws":
            params["type"] = "ws"
            params["path"] = p.get("ws-opts", {}).get("path", "/")
        qs = urllib.parse.urlencode(params)
        pw = urllib.parse.quote(p["password"], safe="")
        return f"trojan://{pw}@{p['server']}:{p['port']}?{qs}#{encoded_name}"

    elif ptype == "ss":
        method_pass = f"{p['cipher']}:{p['password']}"
        encoded = base64.b64encode(method_pass.encode()).decode().rstrip("=")
        return f"ss://{encoded}@{p['server']}:{p['port']}#{encoded_name}"

    elif ptype == "hysteria2":
        params = {}
        if p.get("sni"): params["sni"] = p["sni"]
        if p.get("skip-cert-verify"): params["insecure"] = "1"
        qs = urllib.parse.urlencode(params)
        pw = urllib.parse.quote(p["password"], safe="")
        return f"hysteria2://{pw}@{p['server']}:{p['port']}?{qs}#{encoded_name}"

    elif ptype == "socks5":
        auth = ""
        if p.get("username"):
            auth = f"{urllib.parse.quote(p['username'], safe='')}:{urllib.parse.quote(p.get('password',''), safe='')}@"
        return f"socks5://{auth}{p['server']}:{p['port']}#{encoded_name}"

    return None

def build_v2ray_txt(nodes):
    lines = []
    for n in nodes:
        link = node_to_link(n["raw_config"], n["real_name"])
        if link:
            lines.append(link)
    raw = "\n".join(lines)
    return base64.b64encode(raw.encode("utf-8")).decode("utf-8")

# ============================================================
# 缓存管理
# ============================================================
def get_cache_key():
    """按日期生成cache key"""
    return datetime.now().strftime("%Y-%m-%d")

def save_round_result(round_num, results, proxies):
    """保存单轮测试结果到缓存"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    date_key = get_cache_key()
    # 建立 name -> raw_config 映射
    name_to_config = {p["name"]: p for p in proxies}
    data = {
        "date": date_key,
        "round": round_num,
        "timestamp": datetime.now().isoformat(),
        "results": []
    }
    for name, delay in results.items():
        if name in name_to_config:
            data["results"].append({
                "name": name,
                "delay": delay,
                "server": name_to_config[name].get("server"),
                "port": name_to_config[name].get("port"),
                "type": name_to_config[name].get("type"),
                "raw_config": name_to_config[name],
            })
    path = os.path.join(CACHE_DIR, f"round_{round_num}.json")
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False)
    alive = sum(1 for r in data["results"] if r["delay"] > 0)
    log(f"第{round_num}轮结果已保存: {path} ({len(data['results'])}个节点, {alive}个存活)")

def load_all_rounds():
    """读取所有轮次的结果"""
    rounds = {}
    if not os.path.isdir(CACHE_DIR):
        log(f"[WARN] 缓存目录不存在: {CACHE_DIR}")
        return rounds
    for fname in os.listdir(CACHE_DIR):
        if fname.startswith("round_") and fname.endswith(".json"):
            path = os.path.join(CACHE_DIR, fname)
            try:
                with open(path) as f:
                    data = json.load(f)
                round_num = data.get("round", 0)
                rounds[round_num] = data
                alive = sum(1 for r in data["results"] if r["delay"] > 0)
                log(f"读取第{round_num}轮: {len(data['results'])}个节点, {alive}个存活 ({data.get('timestamp','')})")
            except Exception as e:
                log(f"[WARN] 读取 {fname} 失败: {e}")
    return rounds

def save_node_list(proxies):
    """保存去重后的节点列表（第1轮调用，后续轮次复用）"""
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, "nodes_list.json")
    data = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "timestamp": datetime.now().isoformat(),
        "count": len(proxies),
        "nodes": [{"name": p["name"], "raw_config": {k: v for k, v in p.items() if k != "name"}} for p in proxies],
    }
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False)
    log(f"节点列表已保存: {path} ({len(proxies)}个节点)")

def load_node_list():
    """加载节点列表（第2/3轮调用）"""
    path = os.path.join(CACHE_DIR, "nodes_list.json")
    if not os.path.exists(path):
        log(f"[ERROR] 节点列表不存在: {path}")
        return None
    try:
        with open(path) as f:
            data = json.load(f)
        proxies = []
        for item in data["nodes"]:
            p = dict(item["raw_config"])
            p["name"] = item["name"]
            proxies.append(p)
        log(f"节点列表已加载: {len(proxies)}个节点 (生成于 {data.get('timestamp','')})")
        return proxies
    except Exception as e:
        log(f"[ERROR] 加载节点列表失败: {e}")
        return None

# ============================================================
# 单轮模式
# ============================================================
def run_single_round(round_num, config):
    log(f"{'='*60}")
    log(f"第 {round_num} 轮测试开始")
    log(f"{'='*60}")

    # 第1轮：采集 + 去重 + 保存节点列表
    if round_num == 1:
        log("Phase 1: 采集订阅源")
        all_proxies = collect_all(config)
        log(f"合计原始节点: {len(all_proxies)}")

        log("Phase 2: 去重")
        max_sni = config.get("dedup", {}).get("max_sni_per_ip", 2)
        deduped = dedup(all_proxies, max_sni_per_ip=max_sni)
        from collections import Counter
        log(f"去重后: {len(deduped)}")
        log(f"协议分布: {dict(Counter(p['type'] for p in deduped))}")

        # Phase 2.5: TCP 测活预筛（减轻 URL test 压力）
        test_cfg = config.get("test", {})
        tcp_check = test_cfg.get("tcp_alive_check", True)
        if tcp_check:
            log("Phase 2.5: TCP 测活预筛")
            deduped = tcp_alive_check(
                deduped,
                timeout=test_cfg.get("tcp_timeout_seconds", 5),
                max_workers=test_cfg.get("tcp_concurrency", 50))
            log(f"TCP 测活后待测列表: {len(deduped)}")
            log(f"协议分布: {dict(Counter(p['type'] for p in deduped))}")

        # 重命名并保存节点列表（后续轮次复用）
        renamed = []
        for i, p in enumerate(deduped):
            p2 = dict(p)
            p2["name"] = f"node_{i:04d}"
            renamed.append(p2)
        save_node_list(renamed)
    else:
        # 第2/3轮：直接加载第1轮保存的节点列表，不重新采集
        log(f"Phase 1: 加载第1轮保存的节点列表（跳过采集）")
        renamed = load_node_list()
        if renamed is None:
            log("[ERROR] 无法加载节点列表，退出")
            return
        from collections import Counter
        log(f"加载节点: {len(renamed)}个")
        log(f"协议分布: {dict(Counter(p['type'] for p in renamed))}")

    # 启动Mihomo
    log("Phase 3: 启动 Mihomo")
    stop_mihomo()
    gen_mihomo_config_from_list(renamed)
    if not start_mihomo(config):
        log("[ERROR] Mihomo 启动失败，退出")
        stop_mihomo()
        return

    # URL test（多目标，全通才算存活）
    log("Phase 4: URL test")
    test_cfg = config.get("test", {})
    test_urls = test_cfg.get("test_urls", ["http://www.gstatic.com/generate_204"])
    timeout = test_cfg.get("timeout_seconds", 10)
    log(f"  测试目标: {len(test_urls)} 个 ({', '.join(test_urls)})")
    delays = batch_url_test(renamed, test_urls, timeout)

    alive = sum(1 for v in delays.values() if v > 0)
    log(f"本轮存活: {alive}/{len(renamed)}")

    # 保存结果
    log("Phase 5: 保存结果到缓存")
    save_round_result(round_num, delays, renamed)

    stop_mihomo()
    log(f"第 {round_num} 轮测试完成")

# ============================================================
# 汇总模式
# ============================================================
def run_finalize(config):
    log(f"{'='*60}")
    log("汇总模式: 读取所有轮次结果并生成最终输出")
    log(f"{'='*60}")

    # 1. 读取所有轮次
    rounds = load_all_rounds()
    if not rounds:
        log("[ERROR] 没有找到任何轮次结果，退出")
        return

    log(f"共找到 {len(rounds)} 轮数据: {sorted(rounds.keys())}")

    # 2. 加载节点列表（3轮共用同一批节点，按name匹配）
    node_list = load_node_list()
    if node_list is None:
        log("[WARN] 节点列表不存在，从轮次结果中重建")
        node_list = []
        seen = set()
        for data in rounds.values():
            for r in data["results"]:
                if r["name"] not in seen:
                    seen.add(r["name"])
                    p = dict(r["raw_config"])
                    p["name"] = r["name"]
                    node_list.append(p)

    test_cfg = config.get("test", {})
    min_valid = test_cfg.get("min_valid_rounds", 2)
    top_n = config.get("output", {}).get("top_n", 30)
    output_cfg = config.get("output", {})

    # 3. 按节点名汇总3轮延迟
    node_delays = {}  # name -> [delay1, delay2, ...]
    for round_num, data in sorted(rounds.items()):
        for r in data["results"]:
            node_delays.setdefault(r["name"], []).append(r["delay"])

    log(f"节点列表: {len(node_list)}个, 有测试数据: {len(node_delays)}个")

    # 4. 计算平均延迟，过滤不稳定节点
    stable_nodes = []
    for p in node_list:
        name = p["name"]
        delays = node_delays.get(name, [])
        valid = [d for d in delays if d > 0]
        if len(valid) >= min_valid:
            avg = sum(valid) / len(valid)
            stable_nodes.append({
                "raw_config": p,
                "avg_delay": round(avg),
                "valid_rounds": len(valid),
                "total_rounds": len(delays),
                "delays": delays,
            })

    stable_nodes.sort(key=lambda x: x["avg_delay"])
    log(f"稳定节点（≥{min_valid}轮有效）: {len(stable_nodes)}/{len(node_list)}")

    # 5. IP反查（提前到分组前，对全部稳定节点执行，用于地区分组）
    log("Phase: IP 反查地理位置")
    ip_info = batch_ip_lookup([n["raw_config"] for n in stable_nodes])

    # 6. CF 节点过滤（对中国 IP 通常不可用，限制数量）
    #    先识别 CF 节点，标记后再分组，配额选取时限制 CF 数量
    cf_limit = int(output_cfg.get("max_cf_nodes", 3))
    for n in stable_nodes:
        n["is_cf"] = is_cf_server(n["raw_config"]["server"])
    cf_count = sum(1 for n in stable_nodes if n["is_cf"])
    if cf_count > 0:
        log(f"识别 CF 节点: {cf_count} 个 (限制最多 {cf_limit} 个)")

    # 保存全量稳定节点（含 CN/HK，未做配额截断）——用于 free-nodes-full.yaml
    # （精简版会排除 CN/HK 并截断到 top_n，全量版保留全部供人工选择）
    all_stable_raw = list(stable_nodes)

    # 6.5 排除国家/地区（对中国大陆/香港等出口无意义的节点直接踢掉）
    # 以 ipinfo 主库判定为准（准确、快速；ip-api 复核已弃用——不一致结果反而制造噪音）
    exclude_ccs = set(output_cfg.get("exclude_countries", ["CN", "HK"]))

    def _cc(server):
        info = (ip_info.get(server) or {}).get("info") or {}
        return info.get("countryCode", "")

    before_exclude = len(stable_nodes)
    excluded = [n for n in stable_nodes if _cc(n["raw_config"]["server"]) in exclude_ccs]
    stable_nodes = [n for n in stable_nodes if _cc(n["raw_config"]["server"]) not in exclude_ccs]
    if excluded:
        log(f"排除国家/地区 {sorted(exclude_ccs)}: {before_exclude} → {len(stable_nodes)} "
            f"(踢 {len(excluded)}: {[n['raw_config']['server'] for n in excluded]})")

    # 7. 分层配额选取（亚洲 + 其他 + HTTP 独立配额）
    #    GitHub Actions runner 在美国 → CF/美加节点延迟极低霸榜 → 亚洲节点被挤出
    #    方案：按真实地理位置分组，亚洲节点给独立配额（用户实际在亚洲使用）
    #    HTTP 节点独立配额：以美国为主（美区 Apple ID 等场景需要美国出口）
    region_cfg = output_cfg.get("region_quota", {})
    asia_quota = int(region_cfg.get("asia", 15))
    other_quota = int(region_cfg.get("other", 5))
    http_quota = int(output_cfg.get("http_quota", 10))
    max_same_proto = int(output_cfg.get("max_same_protocol", 8))
    http_prefer_ccs = set(output_cfg.get("http_prefer_countries", ["US"]))
    asia_ccs = set(output_cfg.get("asia_countries",
        ["JP", "SG", "TW", "KR", "TH", "VN", "MY", "PH", "ID", "IN",
         "MO", "BD", "PK", "LK", "KH", "NP"]))

    # HTTP 节点独立分组（不占亚洲/其他名额）
    http_nodes = [n for n in stable_nodes if n["raw_config"]["type"] == "http"]
    non_http = [n for n in stable_nodes if n["raw_config"]["type"] != "http"]
    asia_nodes = [n for n in non_http if _cc(n["raw_config"]["server"]) in asia_ccs]
    other_nodes = [n for n in non_http if _cc(n["raw_config"]["server"]) not in asia_ccs]
    asia_nodes.sort(key=lambda x: x["avg_delay"])
    other_nodes.sort(key=lambda x: x["avg_delay"])
    log(f"地区分组: 亚洲 {len(asia_nodes)} 个, 其他 {len(other_nodes)} 个, HTTP {len(http_nodes)} 个")

    def _quota_select(nodes, quota):
        """按延迟选取节点，同协议最多 max_same_proto 个（协议多样性保护），CF 节点最多 cf_limit 个"""
        selected, proto_count, cf_selected = [], {}, 0
        for n in nodes:
            proto = n["raw_config"]["type"]
            if proto_count.get(proto, 0) >= max_same_proto:
                continue
            if n.get("is_cf") and cf_selected >= cf_limit:
                continue
            selected.append(n)
            proto_count[proto] = proto_count.get(proto, 0) + 1
            if n.get("is_cf"):
                cf_selected += 1
            if len(selected) >= quota:
                break
        return selected

    def _select_http(nodes, quota):
        """HTTP 节点选取：优先指定国家（美国）全加，其余按延迟补足"""
        ordered = sorted(nodes, key=lambda x: (0 if _cc(x["raw_config"]["server"]) in http_prefer_ccs else 1,
                                               x["avg_delay"]))
        return ordered[:quota]

    # 亚洲优先，配额不足时互补
    selected = _quota_select(asia_nodes, asia_quota)
    asia_shortage = asia_quota - len(selected)
    if asia_shortage > 0:
        # 亚洲不足，缺额给其他地区
        selected += _quota_select(other_nodes, other_quota + asia_shortage)
    else:
        selected += _quota_select(other_nodes, other_quota)
    if len(selected) < asia_quota + other_quota:
        # 其他不足，缺额补回亚洲
        selected += _quota_select(asia_nodes, asia_quota + other_quota - len(selected))

    # HTTP 独立配额（美国优先）
    selected_http = _select_http(http_nodes, http_quota)
    selected += selected_http
    log(f"HTTP 选取: {len(selected_http)} 个 (优先 {sorted(http_prefer_ccs)}, 目标 {http_quota})")

    # 去重（互补时可能重叠）
    seen_ids, final_selected = set(), []
    for n in selected:
        if id(n) not in seen_ids:
            seen_ids.add(id(n))
            final_selected.append(n)
    stable_nodes = final_selected
    log(f"配额选取: {len(stable_nodes)} 个 (亚洲{asia_quota}+其他{other_quota}+HTTP{http_quota}, 同协议≤{max_same_proto}个)")
    if len(stable_nodes) > top_n:
        stable_nodes = stable_nodes[:top_n]

    # 7. 生成真实名称
    nodes = []
    for i, n in enumerate(stable_nodes):
        real_name = make_real_name(n["raw_config"], ip_info.get(n["raw_config"]["server"]), i+1)
        info = (ip_info.get(n["raw_config"]["server"]) or {}).get("info") or {}
        nodes.append({
            "real_name": real_name,
            "type": n["raw_config"]["type"],
            "server": n["raw_config"]["server"],
            "port": n["raw_config"]["port"],
            "ip": (ip_info.get(n["raw_config"]["server"]) or {}).get("ip"),
            "country": info.get("country"),
            "city": info.get("city"),
            "isp": info.get("isp"),
            "avg_delay_ms": n["avg_delay"],
            "valid_rounds": n["valid_rounds"],
            "total_rounds": n["total_rounds"],
            "delays": n["delays"],
            "is_cf": n.get("is_cf", False),
            "raw_config": n["raw_config"],
        })

    # 7. 输出
    log("Phase: 生成输出文件")
    output_dir = os.path.join(WORKDIR, config.get("output_dir", "output"))
    os.makedirs(output_dir, exist_ok=True)
    good_threshold = output_cfg.get("good_threshold_ms", 1500)

    good_nodes = [n for n in nodes if n["avg_delay_ms"] < good_threshold]
    log(f"优质节点 (<{good_threshold}ms): {len(good_nodes)}")
    log(f"最终输出节点: {len(nodes)} (top {top_n})")

    meta = {
        "generated_at": datetime.now().isoformat(),
        "total_rounds": len(rounds),
        "rounds_used": sorted(rounds.keys()),
        "total_unique_nodes": len(node_list),
        "total_stable": len(nodes),
        "total_good": len(good_nodes),
        "min_valid_rounds": min_valid,
        "good_threshold_ms": good_threshold,
        "region_quota": {"asia": asia_quota, "other": other_quota, "max_same_protocol": max_same_proto},
        "sources": [s.get("name", s.get("type", "")) for s in config.get("sources", [])],
    }

    # free-nodes.yaml (优质)
    clash_good = build_clash_yaml(good_nodes, output_cfg)
    with open(os.path.join(output_dir, "free-nodes.yaml"), "w") as f:
        yaml.dump(clash_good, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    log(f"  ✓ free-nodes.yaml ({len(good_nodes)}个优质节点)")

    # free-nodes-full.yaml (全量版：含 CN/HK，不做配额截断，按延迟排序，供本机 Clash 人工选择)
    full_nodes = []
    for i, n in enumerate(sorted(all_stable_raw, key=lambda x: x["avg_delay"])):
        real_name = make_real_name(n["raw_config"], ip_info.get(n["raw_config"]["server"]), i+1)
        info = (ip_info.get(n["raw_config"]["server"]) or {}).get("info") or {}
        full_nodes.append({
            "real_name": real_name,
            "type": n["raw_config"]["type"],
            "server": n["raw_config"]["server"],
            "port": n["raw_config"]["port"],
            "ip": (ip_info.get(n["raw_config"]["server"]) or {}).get("ip"),
            "country": info.get("country"),
            "city": info.get("city"),
            "isp": info.get("isp"),
            "avg_delay_ms": n["avg_delay"],
            "valid_rounds": n["valid_rounds"],
            "total_rounds": n["total_rounds"],
            "delays": n["delays"],
            "is_cf": n.get("is_cf", False),
            "raw_config": n["raw_config"],
        })
    clash_full = build_clash_yaml(full_nodes, output_cfg)
    with open(os.path.join(output_dir, "free-nodes-full.yaml"), "w") as f:
        yaml.dump(clash_full, f, allow_unicode=True, default_flow_style=False, sort_keys=False)
    log(f"  ✓ free-nodes-full.yaml ({len(full_nodes)}个全量节点, 含CN/HK, 按延迟排序)")

    # free-nodes.txt (V2Ray)
    txt_content = build_v2ray_txt(good_nodes)
    with open(os.path.join(output_dir, "free-nodes.txt"), "w") as f:
        f.write(txt_content)
    log(f"  ✓ free-nodes.txt (V2Ray/Passwall格式)")

    # nodes.json
    json_data = {"meta": meta, "nodes": nodes}
    with open(os.path.join(output_dir, "nodes.json"), "w") as f:
        json.dump(json_data, f, ensure_ascii=False, indent=2)
    log(f"  ✓ nodes.json (详细数据)")

    # 汇总报告
    log(f"\n{'='*60}")
    log("汇总报告")
    log(f"{'='*60}")
    log(f"测试轮次: {len(rounds)} ({sorted(rounds.keys())})")
    log(f"唯一节点: {len(node_list)}")
    log(f"稳定节点(≥{min_valid}轮): {len(nodes)}")
    log(f"优质节点(<{good_threshold}ms): {len(good_nodes)}")
    # 地区分布
    asia_in_out = sum(1 for n in nodes if _cc(n["server"]) in asia_ccs)
    log(f"地区分布: 亚洲 {asia_in_out} 个, 其他 {len(nodes)-asia_in_out} 个")
    # 协议分布
    from collections import Counter
    proto_dist = Counter(n["type"] for n in nodes)
    log(f"协议分布: {dict(proto_dist)}")
    log(f"\nTOP 10:")
    for i, n in enumerate(nodes[:10]):
        log(f"  {i+1:2d}. {n['real_name']:<40} {n['avg_delay_ms']:>5}ms (有效{n['valid_rounds']}/{n['total_rounds']}轮) {n['type']:<10} {n.get('country','')}")

    log("\n汇总完成!")

# ============================================================
# Main
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="Free Nodes Collector")
    parser.add_argument("--round", type=int, help="单轮测试模式，指定轮次(1/2/3)")
    parser.add_argument("--finalize", action="store_true", help="汇总模式，读取所有轮次结果并输出")
    parser.add_argument("--config", type=str, help="配置文件路径")
    args = parser.parse_args()

    config = load_config(args.config)

    if args.round:
        run_single_round(args.round, config)
    elif args.finalize:
        run_finalize(config)
    else:
        # 默认：完整跑一遍（单轮+汇总），用于本地测试
        log("未指定模式，默认运行完整流程（单轮测试+汇总）")
        run_single_round(1, config)
        run_finalize(config)

if __name__ == "__main__":
    main()
