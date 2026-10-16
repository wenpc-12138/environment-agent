# -*- coding: utf-8 -*-
"""标准驱动公式计算引擎（FormulaEngine，P1）。

公式即数据：formulas.json 声明式注册（绑定标准号/条款/计算类型/输入参数/表达式），
calc(standard, calc_type, data) 自动匹配公式 -> 单位换算 -> 参数绑定 ->
安全表达式计算，返回结果 + 完整计算过程（供 M11 审核验证）。

多行业扩展 = 在 formulas.json 增加公式记录，不改引擎代码。
"""
from __future__ import annotations

import json
import math
import os
import statistics
from typing import Any

_BASE = os.path.dirname(os.path.abspath(__file__))
FORMULAS_PATH = os.path.join(_BASE, "formulas.json")

# 单位族换算（质量浓度族基准 mg/L，体积浓度族基准 mg/m3）
_UNIT_TO_FACTOR = {
    "mg/l": 1.0, "ug/l": 1e-3, "ng/l": 1e-6, "g/l": 1e3,
    "mg/m3": 1.0, "ug/m3": 1e-3, "g/m3": 1e3,
    "-": 1.0, "无量纲": 1.0, "": 1.0,
}
_FAMILY = {
    "mg/l": "conc_mass", "ug/l": "conc_mass", "ng/l": "conc_mass", "g/l": "conc_mass",
    "mg/m3": "conc_vol", "ug/m3": "conc_vol", "g/m3": "conc_vol",
    "-": "none", "无量纲": "none", "": "none",
}
_FAMILY_BASE = {"conc_mass": "mg/l", "conc_vol": "mg/m3", "none": "-"}


class FormulaError(Exception):
    pass


def _norm_unit(u: str) -> str:
    return (u or "").strip().lower()


def _fmt(value: Any) -> Any:
    """结果数值格式化：常规量保留 6 位小数；极小/极大值用科学计数，避免被舍入为 0。"""
    if not isinstance(value, (int, float)):
        return value
    v = float(value)
    if v == 0:
        return 0.0
    mag = abs(v)
    if mag < 1e-5 or mag >= 1e6:
        return float(f"{v:.6e}")
    return round(v, 6)


# ---------------------------------------------------------------- 概率/离群值统计函数
# GB/T 4883-2008 表 A.1 Grubbs 检验临界值（双侧），n=3..30，键为 (0.05, 0.01)
_GRUBBS_CRIT: dict[int, tuple[float, float]] = {
    3: (1.155, 1.155), 4: (1.481, 1.496), 5: (1.715, 1.764), 6: (1.887, 1.973),
    7: (2.020, 2.139), 8: (2.126, 2.274), 9: (2.215, 2.387), 10: (2.290, 2.482),
    11: (2.355, 2.564), 12: (2.412, 2.636), 13: (2.462, 2.699), 14: (2.507, 2.755),
    15: (2.549, 2.806), 16: (2.585, 2.852), 17: (2.620, 2.894), 18: (2.651, 2.932),
    19: (2.681, 2.968), 20: (2.709, 3.001), 21: (2.733, 3.031), 22: (2.758, 3.060),
    23: (2.781, 3.087), 24: (2.802, 3.112), 25: (2.822, 3.135), 26: (2.841, 3.157),
    27: (2.859, 3.178), 28: (2.876, 3.199), 29: (2.893, 3.218), 30: (2.908, 3.236),
}


def gb4883_grubbs(n: Any, alpha: Any = 0.05) -> float | None:
    """查 GB/T 4883-2008 Grubbs 检验临界值；alpha=0.05/0.01，n=3..30，越界返回 None。"""
    t = _GRUBBS_CRIT.get(int(n))
    if not t:
        return None
    return t[0] if float(alpha) >= 0.05 else t[1]


def grubbs_stat(xi: list) -> float:
    """Grubbs 检验统计量 G = max|xi - xbar| / s（样本标准差）。"""
    n = len(xi)
    if n < 2:
        return 0.0
    xbar = sum(xi) / n
    s = math.sqrt(sum((x - xbar) ** 2 for x in xi) / (n - 1))
    if s <= 0:
        return 0.0
    return max(abs(x - xbar) for x in xi) / s


def dixon_q(xi: list) -> float:
    """Dixon 检验统计量（按 n 分段取 r10/r11/r21/r22 的较大值）。"""
    xs = sorted(xi)
    n = len(xs)
    if n < 3:
        return 0.0
    span = xs[-1] - xs[0]
    if span <= 0:
        return 0.0
    if n <= 7:
        q = max((xs[1] - xs[0]) / span, (xs[-1] - xs[-2]) / span)
    elif n <= 10:
        q = max((xs[1] - xs[0]) / (xs[-2] - xs[0]),
                (xs[-1] - xs[-2]) / (xs[-1] - xs[1]))
    elif n <= 13:
        q = max((xs[2] - xs[0]) / (xs[-2] - xs[0]),
                (xs[-1] - xs[-3]) / (xs[-1] - xs[1]))
    else:
        q = max((xs[2] - xs[0]) / (xs[-3] - xs[0]),
                (xs[-1] - xs[-3]) / (xs[-1] - xs[2]))
    return q


def norm_cdf(z: Any) -> float:
    """标准正态累积分布函数 Phi(z)（Abramowitz-Stegun 近似，误差<1e-8）。"""
    z = float(z)
    t = 1.0 / (1.0 + 0.2316419 * abs(z))
    d = 0.3989422804014327 * math.exp(-z * z / 2)
    p = d * t * (0.319381530 + t * (-0.356563782 + t * (1.781477937
        + t * (-1.821255978 + 1.330274429 * t))))
    return 1.0 - p if z > 0 else p


def norm_pdf(z: Any) -> float:
    """标准正态概率密度函数。"""
    z = float(z)
    return 0.3989422804014327 * math.exp(-z * z / 2)


def norm_inv(p: Any) -> float:
    """标准正态分位数（Acklam 近似，误差约 1e-9）。"""
    p = float(p)
    if not 0 < p < 1:
        raise ValueError("p 必须在 (0,1) 之间")
    a = [-39.69683028665376, 220.9460984245205, -275.9285104469687,
         138.357751867269, -30.66479806614716, 2.506628277459239]
    b = [-54.47609879822406, 161.5858368580409, -155.6989798598866,
         66.80131188771972, -13.28068155288572]
    c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838,
         -2.549732539343734, 4.374664141464968, 2.938163982698783]
    d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996,
         3.754408661907416]
    plow = 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p <= 1 - plow:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
               (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
           ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)


def gw_explicit(H0: list, T: Any, S: Any, L: Any, t_total: Any,
                nx: Any, nt: Any, probe: Any = 0.5) -> float:
    """一维承压含水层非稳定流显式有限差分（热传导方程形式，导压系数 a=T/S）。

    H0 初始水头分布（长度>=nx），边界（首尾）固定；probe 探针位置比例（0-1）。
    返回探针处最终水头。注意稳定性条件 r=a·dt/dx² <= 0.5，超出会振荡。
    """
    H = [float(h) for h in H0]
    nx = max(int(nx), 3)
    nt = max(int(nt), 1)
    a = float(T) / float(S) if float(S) else 0.0
    dx = float(L) / (nx - 1)
    dt = float(t_total) / nt
    r = a * dt / (dx * dx) if dx else 0.0
    if len(H) < nx:
        H = H + [H[-1]] * (nx - len(H))
    H = H[:nx]
    for _ in range(nt):
        new = list(H)
        for i in range(1, nx - 1):
            new[i] = H[i] + r * (H[i + 1] - 2 * H[i] + H[i - 1])
        H = new
    idx = int(round((nx - 1) * float(probe)))
    return float(H[idx])


def _sample_dist(rng: Any, spec: Any) -> float:
    """按分布规格抽样：list/tuple=[均值,标准差]（正态）、
    dict: {"dist":"normal"|"uniform"|"triangular", ...}。"""
    if isinstance(spec, (list, tuple)):
        return rng.gauss(float(spec[0]), float(spec[1]))
    dist = (spec or {}).get("dist", "normal")
    if dist == "uniform":
        return rng.uniform(float(spec["low"]), float(spec["high"]))
    if dist == "triangular":
        low, high = float(spec["low"]), float(spec["high"])
        mode = float(spec.get("mode", (low + high) / 2))
        return rng.triangular(low, high, mode)
    return rng.gauss(float(spec.get("mean", 0)), float(spec.get("sd", 1)))


def _spec_sd(spec: Any, rng: Any, m: int = 500) -> float:
    """用抽样估计分布标准差（用于灵敏度贡献率）。"""
    xs = [_sample_dist(rng, spec) for _ in range(m)]
    mean = sum(xs) / len(xs)
    return math.sqrt(sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)) if len(xs) > 1 else 0.0


def mc_uncertainty(expr: str, params: dict, n: Any = 10000,
                   k: Any = 2, seed: Any = 42) -> dict:
    """蒙特卡洛不确定度传播。

    params 每个参数支持：list=[均值,标准差]（正态）、
    {"dist":"uniform","low":..,"high":..}、{"dist":"triangular","low":..,"mode":..,"high":..}。
    返回 {mean, sd, u95, n}，u95 = k·sd（k 默认 2，约 95% 置信）。
    """
    import random
    expr = str(expr)
    n = max(int(n), 100)
    rng = random.Random(int(seed))
    env: dict[str, Any] = dict(_ALLOWED_GLOBALS)
    env["__builtins__"] = {}
    vals: list[float] = []
    for _ in range(n):
        sample: dict[str, Any] = {name: _sample_dist(rng, spec)
                                  for name, spec in params.items()}
        env.update(sample)
        try:
            vals.append(float(eval(expr, env)))
        except Exception:
            vals.append(float("nan"))
    vals = [v for v in vals if v == v]  # 去 NaN
    if not vals:
        return {"mean": None, "sd": None, "u95": None, "n": 0}
    mean = sum(vals) / len(vals)
    sd = math.sqrt(sum((v - mean) ** 2 for v in vals) / (len(vals) - 1)) if len(vals) > 1 else 0.0
    return {"mean": round(mean, 6), "sd": round(sd, 6),
            "u95": round(float(k) * sd, 6), "n": len(vals)}


def mc_sensitivity(expr: str, params: dict, n: Any = 5000,
                   k: Any = 2, seed: Any = 42) -> dict:
    """不确定度灵敏度分析：一阶局部灵敏度系数 + MC 传播 + 相对贡献率。

    返回 {base, sensitivity: {name: {dc, sd, contrib_pct}}, mc}；
    dc 为局部灵敏度系数 df/dx_i（中心差分），contrib_pct 为一阶贡献率
    (dc·sd)²/Σ(dc_j·sd_j)² × 100%。
    """
    import random
    expr = str(expr)
    rng = random.Random(int(seed))
    means: dict[str, float] = {}
    for name, spec in params.items():
        if isinstance(spec, (list, tuple)):
            means[name] = float(spec[0])
        else:
            dist = (spec or {}).get("dist", "normal")
            if dist == "uniform":
                means[name] = (float(spec["low"]) + float(spec["high"])) / 2
            elif dist == "triangular":
                low, high = float(spec["low"]), float(spec["high"])
                means[name] = float(spec.get("mode", (low + high) / 2))
            else:
                means[name] = float(spec.get("mean", 0))
    env: dict[str, Any] = dict(_ALLOWED_GLOBALS)
    env["__builtins__"] = {}
    env.update(means)
    base = float(eval(expr, env))
    sens: dict[str, dict] = {}
    for name in params:
        delta = 1e-4 * max(abs(means[name]), 1e-6)
        env[name] = means[name] + delta
        fp = float(eval(expr, env))
        env[name] = means[name] - delta
        fm = float(eval(expr, env))
        env[name] = means[name]
        dc = (fp - fm) / (2 * delta) if delta else 0.0
        sens[name] = {"dc": round(dc, 6),
                      "sd": round(_spec_sd(params[name], rng), 6)}
    total = sum((sens[name]["dc"] * sens[name]["sd"]) ** 2 for name in params)
    for name in params:
        c = (sens[name]["dc"] * sens[name]["sd"]) ** 2
        sens[name]["contrib_pct"] = round(100 * c / total, 2) if total else 0.0
    mc = mc_uncertainty(expr, params, n, k, seed)
    return {"base": round(base, 6), "sensitivity": sens, "mc": mc}


def _tridiagonal(a: list[float], b: list[float], c: list[float],
                 d: list[float]) -> list[float]:
    """Thomas 算法解三对角系统 a[i]x[i-1] + b[i]x[i] + c[i]x[i+1] = d[i]。"""
    n = len(d)
    cp = [0.0] * n
    dp = [0.0] * n
    cp[0] = c[0] / b[0]
    dp[0] = d[0] / b[0]
    for i in range(1, n):
        m = b[i] - a[i] * cp[i - 1]
        cp[i] = c[i] / m
        dp[i] = (d[i] - a[i] * dp[i - 1]) / m
    x = [0.0] * n
    x[n - 1] = dp[n - 1]
    for i in range(n - 2, -1, -1):
        x[i] = dp[i] - cp[i] * x[i + 1]
    return x


def gw_implicit(H0: list, T: Any, S: Any, L: Any, t_total: Any, nx: Any,
                nt: Any, probe: Any = 0.5, scheme: Any = "cn") -> float:
    """一维地下水非稳定流隐式差分（Thomas 算法，无条件稳定）。

    scheme：'implicit' 全隐式 或 'cn' Crank-Nicolson；首尾边界 Dirichlet 固定。
    返回探针处（默认中点）最终水头。
    """
    nx = max(int(nx), 3)
    nt = max(int(nt), 1)
    a = float(T) / float(S) if float(S) else 0.0
    dx = float(L) / (nx - 1)
    dt = float(t_total) / nt
    r = a * dt / (dx * dx) if dx else 0.0
    H = [float(h) for h in H0][:nx]
    if len(H) < nx:
        H = H + [H[-1]] * (nx - len(H))
    lo = [-r] * nx
    hi = [-r] * nx
    # 边界行解耦（Dirichlet 固定）：a[0]=a[-1]=0、c[0]=c[-1]=0、b=1
    lo[0] = 0; lo[-1] = 0
    hi[0] = 0; hi[-1] = 0
    if str(scheme).lower() == "implicit":
        for _ in range(nt):
            b = [1 + 2 * r] * nx
            d = list(H)
            b[0] = 1; b[-1] = 1
            H = _tridiagonal(lo, b, hi, d)
    else:  # Crank-Nicolson（系数为 -r/2）
        half = r / 2
        lo_cn = [-half] * nx
        hi_cn = [-half] * nx
        lo_cn[0] = 0; lo_cn[-1] = 0
        hi_cn[0] = 0; hi_cn[-1] = 0
        for _ in range(nt):
            b = [1 + r] * nx
            d = [0.0] * nx
            for i in range(1, nx - 1):
                d[i] = half * H[i - 1] + (1 - r) * H[i] + half * H[i + 1]
            d[0] = H[0]; d[-1] = H[-1]
            b[0] = 1; b[-1] = 1
            H = _tridiagonal(lo_cn, b, hi_cn, d)
    idx = int(round((nx - 1) * float(probe)))
    return float(H[idx])


def gw_adi(H0: list, Tx: Any, Ty: Any, S: Any, Lx: Any, Ly: Any, t_total: Any,
           nx: Any, ny: Any, nt: Any, probe_x: Any = 0.5, probe_y: Any = 0.5) -> float:
    """二维承压含水层非稳定流交替方向隐式（ADI，Peaceman-Rachford）。

    H0 二维水头网格（[ny][nx]），四边 Dirichlet 固定；Tx/Ty 两方向导水系数。
    每时间步：先 x 方向隐式（逐行 Thomas）+ y 显式，再 y 隐式 + x 显式。
    无条件稳定。返回探针处最终水头。
    """
    nx = max(int(nx), 3)
    ny = max(int(ny), 3)
    nt = max(int(nt), 1)
    ax = float(Tx) / float(S) if float(S) else 0.0
    ay = float(Ty) / float(S) if float(S) else 0.0
    dx = float(Lx) / (nx - 1)
    dy = float(Ly) / (ny - 1)
    dt = float(t_total) / nt
    rx = ax * dt / (dx * dx) if dx else 0.0
    ry = ay * dt / (dy * dy) if dy else 0.0
    H: list[list[float]] = []
    for j in range(ny):
        row = [float(v) for v in H0[j][:nx]] if j < len(H0) else []
        while len(row) < nx:
            row.append(row[-1] if row else 0.0)
        H.append(row)
    while len(H) < ny:
        H.append(list(H[-1]))
    hx, hy = rx / 2, ry / 2
    for _ in range(nt):
        # 半步 1：x 隐式、y 显式
        mid: list[list[float]] = []
        for j in range(ny):
            row = H[j]
            b = [1 + rx] * nx
            d = [0.0] * nx
            for i in range(1, nx - 1):
                d[i] = hx * row[i - 1] + (1 - rx) * row[i] + hx * row[i + 1]
            d[0] = row[0]; d[-1] = row[-1]
            b[0] = 1; b[-1] = 1
            al = [-hx] * nx; ar = [-hx] * nx
            al[0] = 0; al[-1] = 0
            ar[0] = 0; ar[-1] = 0
            mid.append(_tridiagonal(al, b, ar, d))
        # 半步 2：y 隐式、x 显式
        out = [list(r) for r in mid]
        for i in range(nx):
            col = [mid[j][i] for j in range(ny)]
            b = [1 + ry] * ny
            d = [0.0] * ny
            for j in range(1, ny - 1):
                d[j] = hy * col[j - 1] + (1 - ry) * col[j] + hy * col[j + 1]
            d[0] = col[0]; d[-1] = col[-1]
            b[0] = 1; b[-1] = 1
            al = [-hy] * ny; ar = [-hy] * ny
            al[0] = 0; al[-1] = 0
            ar[0] = 0; ar[-1] = 0
            newcol = _tridiagonal(al, b, ar, d)
            for j in range(ny):
                out[j][i] = newcol[j]
        H = out
    ix = int(round((nx - 1) * float(probe_x)))
    iy = int(round((ny - 1) * float(probe_y)))
    return float(H[iy][ix])


def pct(xi: list, p: Any) -> float:
    """百分位数（线性插值）：p 为百分位（0-100，如 10/50/90）。"""
    xs = sorted(xi)
    n = len(xs)
    if n == 0:
        return 0.0
    if n == 1:
        return float(xs[0])
    idx = (n - 1) * float(p) / 100.0
    lo = int(math.floor(idx))
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return xs[lo] * (1 - frac) + xs[hi] * frac


def well_function(u: Any) -> float:
    """泰斯井函数 W(u) = -gamma - ln(u) + sum((-1)^(n+1) * u^n / (n * n!))。"""
    u = float(u)
    if u <= 0:
        raise ValueError("u 必须大于 0")
    w = -0.5772156649015329 - math.log(u)
    p = u  # p_n = u^n / n!
    n = 1
    sign = 1
    while True:
        term = sign * p / n
        w += term
        if abs(term) < 1e-14 or n > 200:
            break
        sign = -sign
        n += 1
        p = p * u / n
    return w


# 公式表达式可用的白名单函数（运行时引用，定义在统计函数之后）
_ALLOWED_GLOBALS: dict[str, Any] = {
    "math": math, "abs": abs, "round": round, "min": min, "max": max,
    "sum": sum, "len": len, "sqrt": math.sqrt, "log10": math.log10,
    "log": math.log, "pow": pow,
    "zip": zip, "range": range, "enumerate": enumerate, "int": int,
    "median": statistics.median,
    # 概率统计 / GB/T 4883 离群值检验
    "gb4883_grubbs": gb4883_grubbs, "grubbs_stat": grubbs_stat,
    "dixon_q": dixon_q, "norm_cdf": norm_cdf, "norm_pdf": norm_pdf,
    "norm_inv": norm_inv,
    # 噪声统计 / 地下水（泰斯）
    "pct": pct, "well_function": well_function,
    # 数值解：非稳定流有限差分 / 蒙特卡洛不确定度传播
    "gw_explicit": gw_explicit, "mc_uncertainty": mc_uncertainty,
    "gw_implicit": gw_implicit, "gw_adi": gw_adi,
    "mc_sensitivity": mc_sensitivity,
}


def _score(f: dict[str, Any], data: dict) -> int:
    """公式匹配评分：命中数 - 缺必需参数惩罚（同 calc_type 多公式时选最匹配的）。

    如 dilution-ratio 与 mixing-model 同属"水环境影响"且都命中 Q1/Q2，
    后者还缺 C1/C2 必需参数，惩罚后 score 更低，正确选中前者。
    """
    hits = 0
    missing = 0
    for inp in f.get("inputs", []):
        name = inp["name"]
        aliases = inp.get("alias") or []
        if any(k in data for k in [name, *aliases]):
            hits += 1
        elif inp.get("required", True):
            missing += 1
    return hits - missing


def _convert(value: float, from_unit: str, to_unit: str) -> float:
    f, t = _norm_unit(from_unit), _norm_unit(to_unit)
    if f == t:
        return float(value)
    if _FAMILY.get(f) != _FAMILY.get(t):
        raise FormulaError(f"单位不可换算：{from_unit} -> {to_unit}")
    fv = float(value) * _UNIT_TO_FACTOR.get(f, 1.0)
    return fv / _UNIT_TO_FACTOR.get(t, 1.0)


class FormulaEngine:
    def __init__(self, path: str = FORMULAS_PATH):
        with open(path, encoding="utf-8") as fh:
            self.formulas: list[dict[str, Any]] = json.load(fh)
        self._by_id = {f["id"]: f for f in self.formulas}

    def list(self, standard: str = "", calc_type: str = "") -> list[dict[str, Any]]:
        out = []
        for f in self.formulas:
            if standard and standard not in (f.get("standard") or ""):
                continue
            if calc_type and calc_type not in (f.get("calc_type") or ""):
                continue
            out.append({
                "id": f["id"], "name": f.get("name"), "standard": f.get("standard"),
                "clause": f.get("clause"), "calc_type": f.get("calc_type"),
                "desc": f.get("desc"),
            })
        return out

    def find(self, standard: str = "", calc_type: str = "") -> list[dict[str, Any]]:
        return [f for f in self.formulas
                if (not standard
                    or standard == (f.get("standard") or "")
                    or (f.get("standard") or "") == "通用")
                and (not calc_type or calc_type in (f.get("calc_type") or ""))]

    def calc(self, standard: str = "", calc_type: str = "", data: dict | None = None,
             formula_id: str = "") -> dict[str, Any]:
        data = data or {}
        if formula_id:
            cands = [self._by_id.get(formula_id)]
        else:
            cands = self.find(standard, calc_type)
        cands = [c for c in cands if c]
        if not cands:
            raise FormulaError(f"未找到公式：standard={standard!r} calc_type={calc_type!r}")
        # 同类型多公式：按输入参数命中数优先匹配（如不确定度/精密度族）
        if len(cands) > 1:
            cands = sorted(cands, key=lambda f: _score(f, data), reverse=True)
        return self._execute(cands[0], data)

    def _bind_inputs(self, f: dict[str, Any], data: dict) -> tuple[dict[str, Any], list[str]]:
        locals_map: dict[str, Any] = {}
        trace: list[str] = []
        for inp in f.get("inputs", []):
            name = inp["name"]
            unit = (inp.get("unit") or "").strip()
            alias = inp.get("alias") or []
            raw = None
            for key in [name, *alias]:
                if key in data:
                    raw = data[key]
                    break
            if raw is None:
                if inp.get("required", True):
                    raise FormulaError(f"缺少必填参数：{inp.get('label') or name}")
                continue
            is_list = isinstance(raw, list)
            values = raw if is_list else [raw]
            converted = []
            for v in values:
                if isinstance(v, dict) and "value" in v:
                    val = _convert(v["value"], v.get("unit", ""), unit)
                    trace.append(f"{name}[{v.get('unit', '')}->{unit}]={val}")
                elif isinstance(v, (str, dict, list)):
                    val = v  # 表达式/参数分布/二维网格等结构参数原样传入（如蒙特卡洛/ADI）
                    trace.append(f"{name}={type(v).__name__}")
                else:
                    try:
                        val = float(v)
                    except (TypeError, ValueError):
                        val = v
                    trace.append(f"{name}={val}")
                converted.append(val)
            locals_map[name] = converted if is_list else converted[0]
        return locals_map, trace

    def _execute(self, f: dict[str, Any], data: dict) -> dict[str, Any]:
        expr = f["expr"]
        locals_map, trace = self._bind_inputs(f, data)
        env: dict[str, Any] = {"__builtins__": {}}
        env.update(_ALLOWED_GLOBALS)
        env.update(locals_map)
        try:
            value = eval(expr, env)  # noqa: S307（受限白名单环境）
        except Exception as e:
            raise FormulaError(f"表达式求值失败：{expr} ({e})") from e
        out = f.get("output") or {}
        return {
            "ok": True,
            "formula_id": f["id"],
            "name": f.get("name"),
            "standard": f.get("standard"),
            "clause": f.get("clause"),
            "calc_type": f.get("calc_type"),
            "expr": expr,
            "params": locals_map,
            "trace": trace,
            "value": _fmt(value),
            "unit": out.get("unit", ""),
            "output_label": out.get("label", ""),
        }
