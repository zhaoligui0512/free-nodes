#!/usr/bin/env python3
"""CF 节点连通性测试 - 用于检测当前出口对 CF 节点的可达性"""
import json, yaml, subprocess, time, urllib.request, urllib.parse, concurrent.futures, sys, os

def main():
    # 1. 下载最新节点列表
    print("下载最新节点列表...")
    urllib.request.urlretrieve("https://zhaoligui0512.github.io/free-nodes/nodes.json", "/tmp/nodes.json")
    d = json.load(open("/tmp/nodes.json"))

    # 2. 提取 CF 节点
    cf_nodes = [n for n in d["nodes"] if "Cloudflare" in n.get("real_name","") or
                n["server"].startswith("162.159") or n["server"].startswith("188.114") or
                n["server"].startswith("162.35")]
    print(f"CF 节点数: {len(cf_nodes)}")
    for n in cf_nodes:
        print(f"  {n['server']}:{n['port']} {n['real_name']}")

    # 3. 生成 mihomo 配置
    proxies = []
    for n in cf_nodes:
        p = dict(n["raw_config"])
        p["name"] = n["real_name"]
        proxies.append(p)

    config = {
        "mixed-port": 7890,
        "external-controller": "127.0.0.1:9090",
        "proxies": proxies,
        "rules": ["MATCH,DIRECT"]
    }
    with open("/tmp/cf-test.yaml", "w") as f:
        yaml.dump(config, f, allow_unicode=True)

    # 4. 启动 mihomo
    mihomo_bin = sys.argv[1] if len(sys.argv) > 1 else "./mihomo"
    proc = subprocess.Popen([mihomo_bin, "-d", "/tmp", "-f", "/tmp/cf-test.yaml"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(3)

    # 5. 测试
    def test_one(name):
        try:
            encoded = urllib.parse.quote(name, safe="")
            url = f"http://127.0.0.1:9090/proxies/{encoded}/delay?timeout=10000&url=http://www.gstatic.com/generate_204"
            with urllib.request.urlopen(url, timeout=13) as resp:
                data = json.loads(resp.read())
                return name, data.get("delay", 0)
        except:
            return name, 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        results = list(ex.map(lambda n: test_one(n["real_name"]), cf_nodes))

    proc.terminate()

    # 6. 报告
    alive = [(n, d) for n, d in results if d > 0]
    dead = [(n, d) for n, d in results if d == 0]
    print(f"\n=== CF 节点测试结果 ===")
    print(f"存活: {len(alive)}/{len(cf_nodes)}")
    for n, d in sorted(alive, key=lambda x: x[1]):
        print(f"  ✓ {d:>5}ms  {n}")
    if dead:
        print(f"死亡: {len(dead)} 个")
        for n, _ in dead:
            print(f"  ✗ {n}")

if __name__ == "__main__":
    main()
