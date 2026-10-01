# Free Nodes Collector

免费节点自动采集、3轮稳定性测试、IP地理位置反查、多格式发布工具。

## 架构

采用 **3 轮独立测试 + 汇总发布** 架构，避免 GitHub Actions 计费时间浪费在 sleep 上：

```
08:00  Round 1  → 采集→去重→保存节点列表→URL test→commit cache
16:00  Round 2  → 加载节点列表→URL test→commit cache
00:00  Round 3  → 加载节点列表→URL test→汇总(取top30)→发布 GitHub Pages
```

每轮只跑 3-5 分钟，中间间隔完全不计费。3 轮中至少 2 轮存活的节点才算稳定。

## 输出文件

发布到 GitHub Pages 后：

| 文件 | 用途 | 说明 |
|------|------|------|
| `free-nodes.yaml` | Clash/Mihomo 订阅 | 优质节点（延迟 <1500ms） |
| `free-nodes-full.yaml` | Clash/Mihomo 订阅 | 全部 top 30 稳定节点 |
| `free-nodes.txt` | V2Ray/Passwall 订阅 | base64 编码节点链接 |
| `nodes.json` | 节点详细数据 | IP、地理位置、ISP、3轮延迟、平均延迟 |

### 订阅链接（Clash 导入用）

**Raw 链接（GitHub 文件直链，推荐）：**
```
https://raw.githubusercontent.com/zhaoligui0512/free-nodes/main/output/free-nodes.yaml
```

**Pages 链接（GitHub Actions 部署后生效）：**
```
https://zhaoligui0512.github.io/free-nodes/free-nodes.yaml
```

> ⚠️ 注意：不要用 `github.com/.../blob/...` 链接导入！blob 返回的是 HTML 网页，不是 YAML 文件。Clash 等客户端必须用 raw 或 Pages 链接。

## 快速开始

1. Fork / 创建仓库，推送代码
2. Settings → Pages → Source 选 "GitHub Actions"
3. Actions 里手动触发 Round 1 → 等 10 分钟 → Round 2 → 等 10 分钟 → Round 3（测试阶段）
4. 验证通过后，修改 3 个 workflow 的 cron 为生产时间

## 配置说明

所有参数在 `config.yaml`：

```yaml
sources:                    # 订阅源，支持 nomorewalls / mibei / yaml_url
  - name: "NoMoreWalls"
    type: "nomorewalls"
    url: "..."
  - name: "米贝"
    type: "mibei"
    homepage: "https://www.mibei77.com/"

test:
  min_valid_rounds: 2       # 至少几轮存活才算稳定
  timeout_seconds: 10       # 单节点超时
  test_url: "http://www.gstatic.com/generate_204"

output:
  top_n: 30                 # 最终输出节点数
  good_threshold_ms: 1500   # 优质节点延迟阈值
```

### 新增订阅源

```yaml
- name: "我的源"
  type: "yaml_url"          # 任意直接可下载的 Clash YAML
  url: "https://example.com/sub.yaml"
```

## 测试阶段 cron（10分钟间隔）

- `round1.yml`: `0 * * * *`（每小时整点）
- `round2.yml`: `10 * * * *`（每小时10分）
- `round3.yml`: `20 * * * *`（每小时20分 + 发布）

## 生产阶段 cron（每天3次）

- `round1.yml`: `0 0 * * *`（UTC 0:00 = 北京 8:00）
- `round2.yml`: `0 8 * * *`（UTC 8:00 = 北京 16:00）
- `round3.yml`: `0 16 * * *`（UTC 16:00 = 北京 0:00，发布）

## 本地运行

```bash
pip install pyyaml
# 下载 mihomo 和 country.mmdb 到项目目录
python3 collector.py --round 1    # 第1轮（采集+测试）
python3 collector.py --round 2    # 第2轮（复用节点列表）
python3 collector.py --round 3    # 第3轮
python3 collector.py --finalize   # 汇总输出
```

## 节点命名规则

根据真实 IP 反查结果生成，不使用订阅源提供的虚假名称：

```
国家代码-城市-ISP-协议-序号
例：SG-新加坡-Amazon-anytls-01
    JP-东京-UCLOUD-socks5-02
    US-洛杉矶-Psychz-hysteria2-10
```

## 注意事项

- GitHub Actions 服务器在国外，延迟绝对值与国内有差异，但相对排名准确
- 米贝源在 GitHub Actions 中可能因网络原因抓取失败，此时仅使用 NoMoreWalls
- anytls / http 协议仅 Clash/Mihomo 支持，V2Ray 客户端会自动过滤
- 免费节点时效性强，建议每天更新
