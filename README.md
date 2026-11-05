<div align="center">
  <h1>AMiner Open Skills</h1>
  <p>
    <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-2ea44f"></a>
    <a href=".claude-plugin/marketplace.json"><img alt="Version" src="https://img.shields.io/badge/version-1.15.0-0969da"></a>
    <a href="SKILLS.md"><img alt="Skills" src="https://img.shields.io/badge/skills-21-0ea5e9"></a>
    <a href="INSTALL.md"><img alt="Install" src="https://img.shields.io/badge/install-Claude%20Code%20%7C%20Codex%20%7C%20OpenClaw-111827"></a>
    <a href="README.en.md"><img alt="Language" src="https://img.shields.io/badge/language-中文%20%7C%20English-1f6feb"></a>
  </p>
  <p>
    <a href="https://www.aminer.cn/">在线网站</a>
    · <a href="#在线使用科研工作流技能">在线使用</a>
    · <a href="SKILLS.md">技能目录</a>
    · <a href="INSTALL.md">安装指南</a>
    · <a href="https://open.aminer.cn/open/docs">开放平台文档</a>
    · <a href="README.en.md">English</a>
  </p>
  <p>
    <img src="assets/readme-banner-zh-v2.png" alt="AMiner Open Skills：真实学术数据驱动的科研 Skill 库" width="100%">
  </p>
  <p>
    <b>AMiner 网页版：内置智能搜索、AI 阅读、Res Labs、AI2000 等核心功能，访问地址 <a href="https://www.aminer.cn">https://www.aminer.cn</a></b>
  </p>
</div>

---

`aminer-open-skill` 面向科研全流程收录基于 AMiner 学术数据的可复用技能，强调真实学术数据、可验证证据链与可直接使用的科研产物。

## 在线使用：科研工作流技能

以下 7 个技能可在 AMiner 网页版直接使用，点击右侧按钮即可打开，无需安装；也可以按 [安装指南](INSTALL.md) 装到本地 Agent。

| 技能 | 能做什么 | 在&#8288;线&#8288;使&#8288;用 |
|---|---|:---:|
| **论文精读** | 结构化精读、逐句翻译、复现细节审计，按模糊描述定位论文 | [![在线使用](https://img.shields.io/badge/%E5%9C%A8%E7%BA%BF%E4%BD%BF%E7%94%A8_%E2%86%97-1f6feb?style=for-the-badge)](https://www.aminer.cn/?skill=aminer-paper-deep-reading) |
| **论文写作·审稿·返修** | 从零成稿并配真实引用，投稿前模拟审稿，逐条回复审稿意见 | [![在线使用](https://img.shields.io/badge/%E5%9C%A8%E7%BA%BF%E4%BD%BF%E7%94%A8_%E2%86%97-1f6feb?style=for-the-badge)](https://www.aminer.cn/?skill=aminer-journal-paper-write-review-revise) |
| **实验到成稿** | 排查代码与实验问题，把实验结果写成论文，核实方法出处 | [![在线使用](https://img.shields.io/badge/%E5%9C%A8%E7%BA%BF%E4%BD%BF%E7%94%A8_%E2%86%97-1f6feb?style=for-the-badge)](https://www.aminer.cn/?skill=aminer-experiment-to-paper) |
| **学位论文开题到答辩** | 开题调研与查新，逐节起草，落实导师与盲审意见，答辩材料 | [![在线使用](https://img.shields.io/badge/%E5%9C%A8%E7%BA%BF%E4%BD%BF%E7%94%A8_%E2%86%97-1f6feb?style=for-the-badge)](https://www.aminer.cn/?skill=aminer-degree-thesis-proposal-to-defense) |
| **项目申报** | 提取申报要件，凝练科学问题，分节撰写，模拟专家评审 | [![在线使用](https://img.shields.io/badge/%E5%9C%A8%E7%BA%BF%E4%BD%BF%E7%94%A8_%E2%86%97-1f6feb?style=for-the-badge)](https://www.aminer.cn/?skill=aminer-grant-application) |
| **科研选题与导师选择** | 评估方向竞争程度与选题查新，梳理院系导师并逐一对比 | [![在线使用](https://img.shields.io/badge/%E5%9C%A8%E7%BA%BF%E4%BD%BF%E7%94%A8_%E2%86%97-1f6feb?style=for-the-badge)](https://www.aminer.cn/?skill=aminer-topic-advisor-selection) |
| **产业情报与专利** | 产业技术调研，现有技术检索，交底书与权利要求起草，审查意见答复 | [![在线使用](https://img.shields.io/badge/%E5%9C%A8%E7%BA%BF%E4%BD%BF%E7%94%A8_%E2%86%97-1f6feb?style=for-the-badge)](https://www.aminer.cn/?skill=aminer-patent-tech-intelligence) |

## 本地技能

其余 14 个技能安装到本地 Agent（Claude Code、Codex、OpenClaw 等）使用，安装见下方[快速安装](#快速安装)。点击类别后的链接查看完整说明与示例提示词。

**检索与发现** · [示例与详情 →](SKILLS.md#检索与发现)

- [`aminer-free-academic`](skills/aminer-free-academic/SKILL.md)：免费检索论文、学者、机构、期刊、专利的基本信息
- [`aminer-academic-search`](skills/aminer-academic-search/SKILL.md)：完整学术数据查询（29 个 API），含论文实验数据的结构化查询
- [`aminer-daily-paper`](skills/aminer-daily-paper/SKILL.md)：按主题或学者画像推荐论文
- [`aminer-deep-search`](skills/aminer-deep-search/SKILL.zh.md)：为综述收集数百篇候选论文
- [`sota-finder`](skills/sota-finder/SKILL.zh.md)：查找任务的 SOTA 结果，生成带来源的榜单

**阅读与整理** · [示例与详情 →](SKILLS.md#阅读与整理)

- [`aminer-pdf-ocr`](skills/aminer-pdf-ocr/SKILL.zh.md)：将论文 PDF 转换为 Markdown 全文
- [`aminer-exp-extraction`](skills/aminer-exp-extraction/SKILL.md)：从论文 Markdown 抽取实验信息，输出 JSON
- [`scientific-taxonomy`](skills/scientific-taxonomy/SKILL.md)：将一批论文整理为层次分类树
- [`paper-source-trace`](skills/paper-source-trace/SKILL.zh.md)：将论点追踪到引用来源，生成引用关系图

**调研报告** · [示例与详情 →](SKILLS.md#调研报告)

- [`deep-research`](skills/deep-research/SKILL.zh.md)：撰写带引用、证据可追溯的调研报告

**论文实验核查** · [示例与详情 →](SKILLS.md#论文实验核查)

- [`baseline-finder`](skills/baseline-finder/SKILL.md)：核查论文是否遗漏应当比较的实验基线

**引用核查** · [示例与详情 →](SKILLS.md#引用核查)

- [`pdf-citation-verifier`](skills/pdf-citation-verifier/SKILL.zh.md)：核验论文 PDF 的参考文献是否真实存在
- [`structured-reference-audit`](skills/structured-reference-audit/SKILL.zh.md)：保守核验参考文献，查不到不等于伪造
- [`citation-faithfulness`](skills/citation-faithfulness/SKILL.zh.md)：检查引用是否忠于被引原文

## 快速安装

**1. 安装技能**（需要 Node.js 18+，`--skill` 换成需要的技能名，`'*'` 表示全部）：

```bash
npx skills add AMinerOrg/aminer-open-skill --agent claude-code --skill aminer-free-academic --yes
```

Claude Code 用户也可以用插件方式安装，会同时注册技能自带的 slash command：

```text
/plugin marketplace add AMinerOrg/aminer-open-skill
/plugin install aminer-free-academic@aminer-open-skills
```

**2. 配置 Token**：在 [AMiner 控制台](https://open.aminer.cn/open/board?tab=control)生成 Token，并在 Agent 的运行环境中配置：

```bash
export AMINER_API_KEY="<YOUR_TOKEN>"
```

**3. 开始使用**：直接用自然语言描述任务，Agent 会自动选择合适的技能。

手动安装、Python 依赖、OpenClaw 配置与计费说明见 [安装指南](INSTALL.md)。

## 反馈与联系

- 使用问题与 Bug：[GitHub Issues](https://github.com/AMinerOrg/aminer-open-skill/issues)
- 邮件：[report@aminer.cn](mailto:report@aminer.cn)
- API 接入与计费：[AMiner 开放平台](https://open.aminer.cn/open/docs)

本仓库技能由 AMiner 团队维护，暂不接受外部提交新技能。基于 [MIT License](LICENSE) 开源。

## Star 历史

[![Star History Chart](https://api.star-history.com/svg?repos=AMinerOrg/aminer-open-skill&type=Date)](https://star-history.com/#AMinerOrg/aminer-open-skill&Date)
