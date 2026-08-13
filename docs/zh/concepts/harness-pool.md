---
sources:
  - path: ari-core/ari/harness_registry.py
    role: implementation
  - path: ari-core/ari/harness_select.py
    role: implementation
  - path: ari-core/ari/cli/harness.py
    role: implementation
  - path: ari-core/ari/cli/__init__.py
    role: implementation
  - path: ari-core/ari/evaluator/deterministic_evaluator.py
    role: implementation
  - path: ari-core/ari/assurance/problems.py
    role: implementation
  - path: ari-core/config/harnesses/problems
    role: config
  - path: ari-core/tests/test_harness_pool.py
    role: test
  - path: ari-core/tests/test_harness_select.py
    role: test
last_verified: 2026-08-09
---

# Harness 池：选择如何测量，而不是继承唯一的一种方式

**当前状态。** 下文描述的池是*原型*注册表（`ari/harness_registry.py`），
它从 `$ARI_WORKSPACE/harnesses/<task>/` 解析一个 harness。ARI 并不附带这样一棵树，
而本研究所用的那一棵已经退役，因此除非操作者把 `ARI_WORKSPACE` 指向自己的
harness 树，注册表如今什么也解析不出来。被评分的工作改为经由
**pinned problem** —— 一个位于 `ari-core/config/harnesses/problems/` 之下、
由 `ARI_PROBLEM` 命名的目录，携带被钉住的 scaffolding、被钉住的 case 集合
与一个已注册的 oracle，并由单一共享仪器掌管各项 flag 与计时窗口。只有在
`ARI_PROBLEM` 未设置时才会走到注册表。因此下文是这个池的设计以及仍在实现它的
代码，而不是对本仓库中存在的某棵 harness 树的描述。

## 每个任务只有一个 harness 的问题

任务名与测量它的方式，过去是同一件事。`stencil` 既指那个科学问题
（「在这台机器上优化一个三维 7 点 Jacobi stencil」），也指对「我们该如何为它
评分」的某一个特定回答。没有选择，因为根本没有可供选择的对象。

这并不是一个中立的默认。使一次测量值得信任的每一项性质都是一个**选择**，
而每个选择都只被做过一次、且是不可见地做出的，并且至少有一次被证明是错的：

| 选择 | 原本是什么 | 必须变成什么 | 错误选择的代价 |
|---|---|---|---|
| 分母 | 朴素实现 | 有能力的冻结参照实现 | 得分测量的是与「什么都不做」之间的距离 |
| 问题规模 | 工作集落在 LLC 之内 | 工作集落在 LLC 之外 | 研究所需的优化梯度并不存在 |
| 计时窗口 | 墙钟，团队创建在窗口之内 | 内部计时器，团队创建在窗口之外 | 参照实现时间的 37–54% 并不是 kernel |
| 工具链 | 钉在默认值上 | 搜索空间的一部分 | 同一个编译器因一个 flag 变动了 6.8 倍 |
| 环境 | 随环境而定 | 记录并检查 | 一个变量让同一份源码变动了 5.9 倍 |

每一项都是靠发现 harness 是错的而找到的，而不是靠把它与某个替代方案作比较。
池让替代方案得以存在，于是比较在错误发生之前就已可用，而不是之后。

## 池改变了什么

**一个任务拥有多个 harness，而它们可能彼此不一致。** 不一致是一个结果，
而不是需要藏起来的缺陷。如果两个都站得住脚的 harness 把两个候选排出不同的
次序，那么「候选 A 更好」这一主张既是关于代码的主张，也同样是关于 harness 的
主张，读者有权知道这一点。在每个任务只有一个 harness 的情况下，这在结构上是
不可见的。

**选择成为一个显式且被记录的行为。** 与环境记录同样的论证：一项研究若不说明
它选了哪个 harness、从哪些替代方案中选、依据什么理由，那么它在最要紧的那条轴
上是不可复现的。「我们用了最好的 harness」这句话，除非把池和判据写下来，
否则不可证伪。

**稳健性变得可测量。** 有意思的问题不是「候选拿到了什么分数」，而是「换掉
harness 之后这个发现还成立吗」。这个问题在今天甚至无法被提出。

## 声明一个 harness 是为什么而存在的

`harness.toml` 声明如何*运行*一个 harness（entry、kwargs、文件 digest、axis、
scale）。它对这个 harness 是*为什么*而存在的只字未提，而那恰恰是选择所需要的。
`[declares]` 块是机器可读的，并且重要的是，它**在陈述 capability 的同时也陈述
限度**。它被 manifest 的完整性 digest 覆盖，因为它正是池据以选择的东西：编辑
一条已声明的 band，就能在不改动任何一个被评分字节的前提下，改变由哪个 harness
来测量一项研究。

```toml
[declares]
question    = "time to solution against a competent reference, same machine"
denominator = "competent_frozen"      # naive | competent_frozen | anchor_matched | best_known
resolves    = 0.00149                  # measured band: the smallest difference it can separate
cost_s      = 97.7                     # seconds per scoring at the declared repetitions
requires    = ["c_compiler", "openmp"] # capabilities, probed by executing, not by name
sees        = ["memory_bandwidth", "numa_placement", "large_page_policy"]
blind_to    = ["problem_generation"]   # the problem arrives from outside the timed window
```

其中两个字段承担了大部分的分量。

`resolves` 就是那条 **band** —— 它是被测量出来的，而不是被断言的。一个无法分辨
相距小于 0.25% 的两个候选的 harness，不得被选来做一项预期效应为 0.1% 的研究；
选择器现在会拒绝它，也会拒绝任何不带测量日期的 band，因为否则的话，某人敲进去
的数字与某人测出来的数字无从区分。

`blind_to` 记录这个 harness 在结构上看不到什么。这不是猜测：已实测到 large-page
策略让 stencil harness 变动 5.9 倍，却把 GEMM 与 SpMM 留在噪声之内，因为只有
stencil 的候选会自行分配内存，并在计时窗口*之内*对它做 first touch。这是那些
harness 的一项永久性质，它属于 manifest，而不属于某个人的笔记。

## 选择：先靠手工，其次才是自动

手工选择先行，而这不只是出于谨慎。没有一条可供与之分歧的手工基线，自动选择器
就无法被验证 —— 没有任何可以拿来核对它的东西。

    ari harness select --resolve 0.002 --budget-s 120 --must-see large_page_policy

会打印出全部 harness 的排名，并为每一个附上使其合格或不合格的已声明性质，
然后由操作者来选。该命令定义在 `ari/cli/harness.py` 中并有单元测试，但它
**目前并未挂载到 `ari` CLI 上**：`ari harness` 已被 assurance 的 harness 套件
占用，而池这一侧的 app 是被从顶层移除、而不是去遮蔽它，所以今天要拿到这份排名，
只能经由 `ari.harness_select.rank`。当没有任何 harness 合格时它以 2 退出，
因为那本身就是一个结果：要么是需求错了，要么是池里缺一个尚不存在的 harness。
硬要去跑最接近的那一个，得到的是一个数字，而不是一个答案。自动模式将会是对
同一份排名施加一条策略，并以完全相同的方式记录结果；它尚不存在。

**选择器绝不可依据结果来排名。** 一个挑出「给分最高」的那个 harness 的选择器
就是一台 score hacking 机器，而且这会是一次很容易发生的意外：「选择那个让候选
表现最好的 harness」是一句自然的话，也是一条致命的判据。选择依据的是在 run
*之前*就声明好的性质 —— 与问题的契合、分辨率、开销、capability、盲区 ——
绝不依据结果。这一点由结构而非惯例来强制：选择器模块不导入任何能加载 harness、
读取结果文件或运行任何东西的模块，并有一个测试从它的 AST 上断言这一点。两道
防线都已被验证为在被违反时会失败。

## 这不会改变什么

完整性 pin、对被修改文件的 `refusing to score` 行为，以及「一个节点的编辑无法
抵达评分器」这条规则，全都原封不动。注册仍然以 manifest 的存在为准。一个每任务
拥有多个 harness 的池，对这些性质的需要只多不少。

## 制作一个变体

一个变体是一个**独立的目录** —— 这让每个 harness 各自保持内容寻址 —— 但它
**不**复制代码，而是链接过去：

    harnesses/gemm_incache/
        gemm_harness.py -> ../gemm/gemm_harness.py     # symlink
        gemm_kernels    -> ../gemm/gemm_kernels        # symlink
        experiment.md   -> ../gemm/experiment.md       # symlink
        harness.toml                                   # the only real file

digest 是*穿过*符号链接来读取的，正是这一点让这种做法不只是方便，而是正确的：
两份 manifest 钉住的是同一批字节，因此编辑那份共享的源会**同时**打断两个变体的
pin。若采用复制，就会得到覆盖两个文件的两份 pin，而这两个文件会悄悄地各自漂移，
第二份副本会继续拿着第一份早已修好的 scaffolding 去评分。

所有不同之处都存在于 manifest 中：

    [harness]
    task = "gemm"                  # the question it answers; the pool it joins

    [measure_kwargs]
    shapes = [[512, 512, 512]]     # the preliminary problem: 6.0 MiB, fits in L2

把问题定义放进 `[measure_kwargs]` 而不是放进环境变量，正是关键所在。
`ARI_STENCIL_SHAPES` 能在不移动任何一个被钉住的字节、不改变 manifest 哈希、
也不触及 `measure_kwargs` 的情况下，整个替换掉被评分的问题 —— 而这个 harness
会继续宣称一条它是在另一个问题上测出来的 band。被声明的 kwarg 处在 digest
之内。若某个旋钮必须留在环境里，就把它连同 band 被测量时所处的取值一起写进
`[declares.band_conditions]`，于是当一次 run 与之不符时，选择器会拒绝那条
band。这能检测出问题；而一个被声明的 kwarg 是直接消除问题。

为一个任务注册第二个 harness 是刻意**破坏性**的：此时 `load("gemm")` 会拒绝，
每一个调用方都必须指名一个 harness（或设置 `ARI_HARNESS`）。这是设计在起作用
—— 另一种做法会让一个本质上属于某个目录名的得分，被当作该任务的性质来报告 ——
但这也意味着，向一项进行中的研究里加入一个变体是一个决定，而不是一次便利。

## 尚未解决

- **由谁来测 `resolves`。** band 必须被测量，而这对每个变体都要花掉节点时间
  （选择器的拒绝信息点名 `tools/measure_resolution_band.py`，而它并不是本仓库
  中的一个文件）；并且一个变体不得继承它所派生自的那份配置的 band —— 那个数字
  属于另一份配置。manifest 携带该次测量的日期与重复次数，而选择器会拒绝没有
  日期的 band，因此一个未经测量的变体在分辨率这一项上根本无法被选中。选择器
  点名处于这一状态的那两个 harness（`erfc`、`meshpart`）住在已退役的 workspace
  树里，因此从本仓库可以触及的 harness 之中，根本没有任何一个声明了 band。
- **跨 harness 的一致性。** 要报告它，就需要一个「同一个候选在两个 harness
  之下」的定义；对冻结参照实现来说这很直接，对可能在两者之下都编译不过的
  智能体生成代码来说就没那么直接了。在它出现之前，池让你可以*选择*一个
  harness，却还不能追问一个发现是否经得起这个选择 —— 而那正是池被造出来所要
  回答的问题。
- **自动选择。** 排名是有的；但没有任何东西会对它施加一条策略并去运行胜出者。
  无论将来由什么来做这件事，它都必须像手工路径已经做的那样，原样记录下选择与
  各个备选。
