# 决策记录 / DECISIONS

> 本文件记录 free-nodes 项目已确认的决策和待讨论项。每次方案调整前先看这里。

## 当前流程（已确认）

- 三轮架构：R1 采集+测试 → R2 测试 → R3 测试+汇总+发布
- cron：R1 北京 08:00 / R2 北京 16:00 / R3 北京 00:00（次日）
- R3 finalize 后部署 GitHub Pages + commit output/ 和 .cache/
- 测试出口：GitHub Actions runner → 用户长沙路由器 WireGuard 链式（mihomo wireguard outbound + dialer-proxy）
- 测试目标：gstatic / chatgpt / youtube / meta 四目标全通
- 输出：free-nodes.yaml（路由精简 30，屏蔽 CN/HK）+ free-nodes-full.yaml（PC 全量，含 CN/HK）+ free-nodes.txt + nodes.json

## 已确认的事实（有实测数据支撑）

1. **免费节点池寿命极短（小时级）**：10-01 那批 30 个非 HTTP 节点，到 10-02 深夜 100% 死亡（16 个在名单 0/3 全死 + 14 个已被淘汰）。不是流程 bug，是池子本身特性。
2. **CF vless 全灭原因**：源里 vless 不带 ECH（173 个 vless 带 ECH=0），普通 CF vless 被 GFW SNI 特征识别重置；带 ECH 的 CF 节点（用户自建）从北京能通。parse_vless 已修复保留 ECH（cfa65f5）。
3. **Passwall2 不支持 Clash `type: http`**：订阅转换时"找不到可使用二进制"自动丢弃。路由版里 http 节点对 Passwall 是废的。
4. **链式 wg 隧道有损耗**：北京直测非 HTTP 19/42 vs 链式 8-14/29-37。新参数（timeout 15s / threshold 3000ms）已放宽，R1 非 HTTP 回升到 14。
5. **ipinfo 单库为准**：ip-api 对 GCP/云段误判多（如 137.175.22.5 标成 CN 山西，实际 US San Jose），已弃用双库复核。米贝的节点名（US/新加坡等）大多是乱标，以 ipinfo 反查为准。
6. **chatgpt 作为存活判定目标两宗罪**：000 超时误杀（KR 节点 3/4 通只挂 chatgpt 被判死）+ 403 漏判（香港节点 chatgpt 403 被 mihomo delay 判通）。

## 待决策项（讨论过，未拍板）

### D1. 存活判定：四目标 vs 三目标
- 现状：gstatic/chatgpt/youtube/meta 四目标全通才算活
- 备选：三目标（gstatic/youtube/meta 全通即活，chatgpt 仅标注不判定）
- 影响：能捞回 KR 那种"3/4 通只挂 chatgpt"的节点（Google/YouTube 完全可用）
- 关联：用户主要用 Gemini/GPT，chatgpt 不通对他有价值损失；但 PC 全量版可人工选

### D2. 配额策略：固定配额 vs 自适应
- 现状：亚洲 15 + 其他 5 + HTTP 10 = 30
- 问题：非 HTTP 存活只有 8 个时配额填不满，US_7/US_13 这种 2/3 轮稳定但延迟 ~2100ms 的被"其他组 5 名额"挤掉
- 备选：非 HTTP < 20 时全保留不截断，> 20 才按配额排序

### D3. 扩源（最大杠杆）
- 现状：NoMoreWalls + 米贝（2 个源）
- 方向：用户提供好的 Free 源，我验证可用性+去重质量后加入
- 预期：非 HTTP 存活从 8 → 20-40

### D4. 路由版输出是否剔除 http
- 现状：free-nodes.yaml 含 http 10 个（Passwall 自动丢弃，剩 8 个非 HTTP）
- 备选：路由版生成时直接过滤 type: http，订阅里全是 Passwall 能用的（避免"20 多个只剩 8 个"的误导）
- PC 全量版保留 http（Clash 支持）

### D5. 采集频率
- 现状：每天 1 次完整采集（R1 早 8 点）
- 备选：每 6-8 小时采集一次（提高订阅时刻新鲜度，免费池小时级波动）
- 成本：Actions 分钟数增加，需评估额度

### D6. 香港节点处理
- 现状：路由版屏蔽 CN/HK（exclude_countries=[CN,HK]）
- 背景：香港节点看 YouTube/Google 延迟低但 AI 调用受限（与中国法律政策一致），URL test 自动选可能被香港低延迟节点抢占
- 决策：已屏蔽路由版，全量版保留供人工选。后续观察稳定性再评估是否需要 curl+状态码校验的中等改造

## 历史版本对比（节点协议构成）

| 版本 | 时间 | 节点数 | vless | anytls | ss | http | 其他 |
|---|---|---|---|---|---|---|---|
| bf14eed | 10-01 17:38 | 30 | 16 | 7 | 5 | 0 | trojan1+socks5 1 |
| 04eae58 | 10-01 18:44 | 30 | 16 | 8 | 3 | 1 | trojan1+socks5 1 |
| c9646d9 | 10-02 16:19 | 26 | 14 | 2 | 5 | 1 | trojan1+socks5 3 |
| 3225439 | 10-02 22:48 | 18 | 6 | 2 | 0 | 10 | - |
| HEAD | 10-03 | 18 | 6 | 2 | 0 | 10 | - |
