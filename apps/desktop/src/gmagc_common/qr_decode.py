"""Чтение QR-кода из серого изображения на чистом Python (только стандартная библиотека).

Нужно телефону на Qt: у Android нет библиотеки zbar, а Qt не умеет читать штрихкоды. Поддерживаются версии 1–10
(до 57×57 модулей: ссылка подключения GMAGC короткая), все уровни коррекции ошибок, поворот на любой угол и
небольшой перекос (аффинное преобразование по трём поисковым узорам), режимы: цифры, буквы+цифры, байты.
Коррекция ошибок по Риду—Соломону исправляет повреждённые кодовые слова.
"""

from __future__ import annotations

import math

# ---- поле GF(256), полином 0x11D ---------------------------------------------------------------
_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= 0x11D
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def _mul(a: int, b: int) -> int:
    return 0 if a == 0 or b == 0 else _EXP[_LOG[a] + _LOG[b]]


def _div(a: int, b: int) -> int:
    return 0 if a == 0 else _EXP[(_LOG[a] - _LOG[b]) % 255]


def _poly_eval(poly: list[int], x: int) -> int:
    """Значение многочлена (старший коэффициент первым) в точке x."""
    result = 0
    for coefficient in poly:
        result = _mul(result, x) ^ coefficient
    return result


def _poly_low_eval(poly: list[int], x: int) -> int:
    """Значение многочлена (младший коэффициент первым) в точке x."""
    result = 0
    for coefficient in reversed(poly):
        result = _mul(result, x) ^ coefficient
    return result


def rs_correct(block: list[int], ec_count: int) -> list[int] | None:
    """Исправляет ошибки в блоке (данные + ec_count проверочных слов); None — исправить нельзя."""
    syndromes = [_poly_eval(block, _EXP[i]) for i in range(ec_count)]
    if not any(syndromes):
        return block
    # Берлекэмп—Мэсси: многочлен локаторов ошибок (младший коэффициент первым)
    locator, previous = [1], [1]
    length_l, shift, last_delta = 0, 1, 1
    for step in range(ec_count):
        delta = syndromes[step]
        for i in range(1, length_l + 1):
            if i < len(locator):
                delta ^= _mul(locator[i], syndromes[step - i])
        if delta == 0:
            shift += 1
            continue
        factor = _div(delta, last_delta)
        updated = locator + [0] * max(0, len(previous) + shift - len(locator))
        for i, coefficient in enumerate(previous):
            updated[i + shift] ^= _mul(factor, coefficient)
        if 2 * length_l <= step:
            previous, last_delta = locator, delta
            length_l = step + 1 - length_l
            shift = 1
        else:
            shift += 1
        locator = updated
    while len(locator) > 1 and locator[-1] == 0:
        locator.pop()
    errors = len(locator) - 1
    if errors == 0 or errors * 2 > ec_count:
        return None
    size = len(block)
    powers = [size - 1 - i for i in range(size) if _poly_low_eval(locator, _EXP[(255 - (size - 1 - i)) % 255]) == 0]
    if len(powers) != errors:
        return None
    # многочлен вычислителя: Ω = S·Λ mod x^ec, затем формула Форни
    omega = [0] * ec_count
    for i in range(ec_count):
        for j in range(min(i + 1, len(locator))):
            omega[i] ^= _mul(locator[j], syndromes[i - j])
    corrected = list(block)
    for power in powers:
        x_inverse = _EXP[(255 - power) % 255]
        numerator = _poly_low_eval(omega, x_inverse)
        derivative = 0
        for i in range(1, len(locator), 2):
            derivative ^= _mul(locator[i], _EXP[(_LOG[x_inverse] * (i - 1)) % 255])
        if derivative == 0:
            return None
        corrected[size - 1 - power] ^= _mul(_EXP[power], _div(numerator, derivative))
    if any(_poly_eval(corrected, _EXP[i]) for i in range(ec_count)):
        return None
    return corrected


# ---- таблицы версий 1–10 ---------------------------------------------------------------------------
# версия → уровень → (проверочных слов на блок, [(число блоков, данных в блоке), ...])
_BLOCKS: dict[int, dict[str, tuple[int, list[tuple[int, int]]]]] = {
    1: {"L": (7, [(1, 19)]), "M": (10, [(1, 16)]), "Q": (13, [(1, 13)]), "H": (17, [(1, 9)])},
    2: {"L": (10, [(1, 34)]), "M": (16, [(1, 28)]), "Q": (22, [(1, 22)]), "H": (28, [(1, 16)])},
    3: {"L": (15, [(1, 55)]), "M": (26, [(1, 44)]), "Q": (18, [(2, 17)]), "H": (22, [(2, 13)])},
    4: {"L": (20, [(1, 80)]), "M": (18, [(2, 32)]), "Q": (26, [(2, 24)]), "H": (16, [(4, 9)])},
    5: {"L": (26, [(1, 108)]), "M": (24, [(2, 43)]), "Q": (18, [(2, 15), (2, 16)]), "H": (22, [(2, 11), (2, 12)])},
    6: {"L": (18, [(2, 68)]), "M": (16, [(4, 27)]), "Q": (24, [(4, 19)]), "H": (28, [(4, 15)])},
    7: {"L": (20, [(2, 78)]), "M": (18, [(4, 31)]), "Q": (18, [(2, 14), (4, 15)]), "H": (26, [(4, 13), (1, 14)])},
    8: {"L": (24, [(2, 97)]), "M": (22, [(2, 38), (2, 39)]), "Q": (22, [(4, 18), (2, 19)]), "H": (26, [(4, 14), (2, 15)])},
    9: {"L": (30, [(2, 116)]), "M": (22, [(3, 36), (2, 37)]), "Q": (20, [(4, 16), (4, 17)]), "H": (24, [(4, 12), (4, 13)])},
    10: {"L": (18, [(2, 68), (2, 69)]), "M": (26, [(4, 43), (1, 44)]), "Q": (24, [(6, 19), (2, 20)]), "H": (28, [(6, 15), (2, 16)])},
}
_ALIGNMENT = {1: [], 2: [6, 18], 3: [6, 22], 4: [6, 26], 5: [6, 30], 6: [6, 34], 7: [6, 22, 38], 8: [6, 24, 42], 9: [6, 26, 46], 10: [6, 28, 50]}
_LEVEL_BITS = {0b01: "L", 0b00: "M", 0b11: "Q", 0b10: "H"}
_ALNUM = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:"


def _format_words() -> dict[int, int]:
    """Все 32 допустимых слова формата (после маскирования 0x5412) → 5 бит данных."""
    words = {}
    for data in range(32):
        value = data << 10
        for shift in range(14, 9, -1):
            if value & (1 << shift):
                value ^= 0x537 << (shift - 10)
        words[((data << 10) | value) ^ 0x5412] = data
    return words


_FORMATS = _format_words()


def _decode_format(bits: int) -> int | None:
    best, distance = None, 4
    for word, data in _FORMATS.items():
        d = bin(word ^ bits).count("1")
        if d < distance:
            best, distance = data, d
    return best


# ---- изображение → двоичная матрица ----------------------------------------------------------------
def binarize(gray: bytes, width: int, height: int) -> list[bytearray]:
    """Тёмное = 1. Порог считается по блокам: снимок с неравномерным светом читается лучше глобального порога."""
    block = max(16, min(width, height) // 12)
    thresholds: dict[tuple[int, int], float] = {}
    for by in range(0, height, block):
        for bx in range(0, width, block):
            low, high = 255, 0
            for y in range(by, min(by + block, height), 2):
                row = gray[y * width + bx : y * width + min(bx + block, width)]
                if row:
                    low, high = min(low, min(row)), max(high, max(row))
            thresholds[(bx // block, by // block)] = (low + high) / 2 if high - low > 24 else -1.0
    global_mean = sum(gray[:: max(1, len(gray) // 4000)]) / max(1, len(gray[:: max(1, len(gray) // 4000)]))
    rows = []
    for y in range(height):
        out = bytearray(width)
        base = y * width
        for x in range(width):
            limit = thresholds[(x // block, y // block)]
            out[x] = 1 if gray[base + x] < (limit if limit >= 0 else global_mean) else 0
        rows.append(out)
    return rows


# ---- поиск поисковых узоров -----------------------------------------------------------------------------
def _runs(line) -> list[tuple[int, int, int]]:
    """Серии одинаковых значений: (значение, начало, длина)."""
    result, start = [], 0
    for i in range(1, len(line) + 1):
        if i == len(line) or line[i] != line[start]:
            result.append((line[start], start, i - start))
            start = i
    return result


def _ratio_ok(lengths: list[int]) -> bool:
    total = sum(lengths)
    if total < 7:
        return False
    unit = total / 7.0
    limits = (unit / 2 + 0.1, unit / 2 + 0.1, 1.5 * unit + 0.1, unit / 2 + 0.1, unit / 2 + 0.1)
    return all(abs(length - expected) < limit for length, expected, limit in zip(lengths, (unit, unit, 3 * unit, unit, unit), limits, strict=True))


def _cross_check(bw, cx: float, cy: float, unit: float) -> bool:
    """Проверка узора 1:1:3:1:1 по вертикали и диагоналям от найденного центра."""
    height, width = len(bw), len(bw[0])
    for dx, dy in ((0, 1), (1, 1), (1, -1)):
        line = []
        for step in range(-int(4.5 * unit) - 1, int(4.5 * unit) + 2):
            x, y = math.floor(cx + dx * step), math.floor(cy + dy * step)
            line.append(bw[y][x] if 0 <= x < width and 0 <= y < height else 0)
        runs = _runs(line)
        found = False
        for index in range(len(runs) - 4):
            group = runs[index : index + 5]
            if group[0][0] == 1 and _ratio_ok([g[2] for g in group]):
                found = True
                break
        if not found:
            return False
    return True


def find_finders(bw: list[bytearray]) -> list[tuple[float, float, float]]:
    """Центры поисковых узоров и размер модуля: [(x, y, модуль), …]."""
    found: list[tuple[float, float, float]] = []
    height = len(bw)
    for y in range(height):
        runs = _runs(bw[y])
        for index in range(len(runs) - 4):
            group = runs[index : index + 5]
            if group[0][0] != 1 or not _ratio_ok([g[2] for g in group]):
                continue
            total = sum(g[2] for g in group)
            unit = total / 7.0
            middle = group[2]
            cx = middle[1] + middle[2] / 2.0
            column = int(cx)  # координаты считаются от левого края пикселя: центр 37.5 лежит в пикселе 37
            top = bottom = y
            while top > 0 and bw[top - 1][column]:
                top -= 1
            while bottom + 1 < height and bw[bottom + 1][column]:
                bottom += 1
            if not 1.5 * unit < bottom - top + 1 < 4.5 * unit:  # центральный тёмный квадрат 3×3 модуля
                continue
            cy = (top + bottom + 1) / 2.0
            if not _cross_check(bw, cx, cy, unit):
                continue
            if any(abs(fx - cx) < 2 * unit and abs(fy - cy) < 2 * unit for fx, fy, _ in found):
                continue
            found.append((cx, cy, unit))
    return found


# ---- декодирование матрицы ----------------------------------------------------------------------------------
def _sample(bw, x: float, y: float) -> int:
    height, width = len(bw), len(bw[0])
    xi, yi = math.floor(x), math.floor(y)
    if not (0 <= xi < width and 0 <= yi < height):
        return 0
    return bw[yi][xi]


def _grid(bw, tl, tr, bl, dimension: int) -> list[list[int]]:
    """Матрица модулей по трём центрам поисковых узоров (аффинное соответствие)."""
    span = dimension - 7.0
    ux, uy = (tr[0] - tl[0]) / span, (tr[1] - tl[1]) / span
    vx, vy = (bl[0] - tl[0]) / span, (bl[1] - tl[1]) / span
    matrix = []
    for row in range(dimension):
        line = []
        for col in range(dimension):
            # центр поискового узора — центр модуля с номером 3 (номера от 0): смещения считаются от него
            x = tl[0] + (col - 3) * ux + (row - 3) * vx
            y = tl[1] + (col - 3) * uy + (row - 3) * vy
            # голосование по трём точкам внутри модуля устойчивее одиночной выборки
            votes = _sample(bw, x, y) * 2 + _sample(bw, x + 0.25 * ux, y + 0.25 * uy) + _sample(bw, x - 0.25 * vx, y - 0.25 * vy)
            line.append(1 if votes >= 2 else 0)
        matrix.append(line)
    return matrix


def _function_mask(version: int) -> list[list[bool]]:
    """Модули, занятые служебными узорами (в них кодовые слова не лежат)."""
    dimension = 17 + 4 * version
    mask = [[False] * dimension for _ in range(dimension)]

    def block(x0: int, y0: int, w: int, h: int) -> None:
        for y in range(max(y0, 0), min(y0 + h, dimension)):
            for x in range(max(x0, 0), min(x0 + w, dimension)):
                mask[y][x] = True

    block(0, 0, 9, 9)
    block(dimension - 8, 0, 8, 9)
    block(0, dimension - 8, 9, 8)
    block(6, 0, 1, dimension)
    block(0, 6, dimension, 1)
    centers = _ALIGNMENT[version]
    for cy in centers:
        for cx in centers:
            if (cx, cy) in ((6, 6), (6, centers[-1]), (centers[-1], 6)):
                continue
            block(cx - 2, cy - 2, 5, 5)
    if version >= 7:
        block(dimension - 11, 0, 3, 6)
        block(0, dimension - 11, 6, 3)
    return mask


_MASKS = (
    lambda r, c: (r + c) % 2 == 0,
    lambda r, c: r % 2 == 0,
    lambda r, c: c % 3 == 0,
    lambda r, c: (r + c) % 3 == 0,
    lambda r, c: (r // 2 + c // 3) % 2 == 0,
    lambda r, c: (r * c) % 2 + (r * c) % 3 == 0,
    lambda r, c: ((r * c) % 2 + (r * c) % 3) % 2 == 0,
    lambda r, c: ((r + c) % 2 + (r * c) % 3) % 2 == 0,
)


def _read_format(matrix: list[list[int]]) -> tuple[str, int] | None:
    """Уровень коррекции и номер маски из двух копий слова формата (биты читаются старшим вперёд)."""
    dimension = len(matrix)
    first_cells = [(x, 8) for x in range(6)] + [(7, 8), (8, 8), (8, 7)] + [(8, y) for y in range(5, -1, -1)]
    second_cells = [(8, dimension - 1 - i) for i in range(7)] + [(dimension - 8 + i, 8) for i in range(8)]

    def word(cells: list[tuple[int, int]]) -> int:
        value = 0
        for x, y in cells:
            value = (value << 1) | matrix[y][x]
        return value

    data = _decode_format(word(first_cells))
    if data is None:
        data = _decode_format(word(second_cells))
    if data is None:
        return None
    return _LEVEL_BITS[data >> 3], data & 7


def _codewords(matrix: list[list[int]], version: int, mask_id: int) -> list[int]:
    dimension = len(matrix)
    function = _function_mask(version)
    mask = _MASKS[mask_id]
    bits: list[int] = []
    col = dimension - 1
    upward = True
    while col > 0:
        if col == 6:
            col -= 1
        rows = range(dimension - 1, -1, -1) if upward else range(dimension)
        for row in rows:
            for c in (col, col - 1):
                if not function[row][c]:
                    bit = matrix[row][c]
                    if mask(row, c):
                        bit ^= 1
                    bits.append(bit)
        upward = not upward
        col -= 2
    return [int("".join(map(str, bits[i : i + 8])), 2) for i in range(0, len(bits) - len(bits) % 8, 8)]


def _data_bytes(codewords: list[int], version: int, level: str) -> bytes | None:
    ec, groups = _BLOCKS[version][level]
    sizes = [size for count, size in groups for _ in range(count)]
    total_data = sum(sizes)
    needed = total_data + ec * len(sizes)
    if len(codewords) < needed:
        return None
    blocks = [[] for _ in sizes]
    index = 0
    for i in range(max(sizes)):
        for b, size in enumerate(sizes):
            if i < size:
                blocks[b].append(codewords[index])
                index += 1
    for _ in range(ec):
        for b in range(len(sizes)):
            blocks[b].append(codewords[index])
            index += 1
    result = bytearray()
    for block, size in zip(blocks, sizes, strict=True):
        fixed = rs_correct(block, ec)
        if fixed is None:
            return None
        result.extend(fixed[:size])
    return bytes(result)


def _parse(data: bytes, version: int) -> str | None:
    bits = "".join(f"{b:08b}" for b in data)
    pos = 0
    out = bytearray()
    text = ""
    counts = (10, 9, 8) if version <= 9 else (12, 11, 16)
    while pos + 4 <= len(bits):
        mode = int(bits[pos : pos + 4], 2)
        pos += 4
        if mode == 0:
            break
        if mode == 1:
            n = int(bits[pos : pos + counts[0]], 2)
            pos += counts[0]
            digits = ""
            while n >= 3:
                digits += f"{int(bits[pos : pos + 10], 2):03d}"
                pos, n = pos + 10, n - 3
            if n == 2:
                digits += f"{int(bits[pos : pos + 7], 2):02d}"
                pos += 7
            elif n == 1:
                digits += f"{int(bits[pos : pos + 4], 2):d}"
                pos += 4
            text += digits
        elif mode == 2:
            n = int(bits[pos : pos + counts[1]], 2)
            pos += counts[1]
            while n >= 2:
                value = int(bits[pos : pos + 11], 2)
                text += _ALNUM[value // 45] + _ALNUM[value % 45]
                pos, n = pos + 11, n - 2
            if n == 1:
                text += _ALNUM[int(bits[pos : pos + 6], 2)]
                pos += 6
        elif mode == 4:
            n = int(bits[pos : pos + counts[2]], 2)
            pos += counts[2]
            chunk = bytes(int(bits[pos + 8 * i : pos + 8 * i + 8], 2) for i in range(n))
            pos += 8 * n
            try:
                text += chunk.decode("utf-8")
            except UnicodeDecodeError:
                text += chunk.decode("latin-1")
        elif mode == 7:
            pos += 8  # ECI: назначение кодировки игнорируем, байты читаются как UTF-8
        else:
            return None
    del out
    return text


def decode_matrix(matrix: list[list[int]]) -> str | None:
    """Текст из матрицы модулей (1 — тёмный); None, если прочитать не удалось."""
    dimension = len(matrix)
    if dimension < 21 or (dimension - 17) % 4 or (dimension - 17) // 4 > 10:
        return None
    version = (dimension - 17) // 4
    info = _read_format(matrix)
    if info is None:
        return None
    level, mask_id = info
    data = _data_bytes(_codewords(matrix, version, mask_id), version, level)
    if data is None:
        return None
    return _parse(data, version)


def _order(triple):
    """Верхний левый — вершина прямого угла; остальные — по знаку векторного произведения (верхний правый, нижний левый)."""
    best = None
    for i in range(3):
        a = triple[i]
        b, c = (triple[j] for j in range(3) if j != i)
        v1, v2 = (b[0] - a[0], b[1] - a[1]), (c[0] - a[0], c[1] - a[1])
        n1, n2 = math.hypot(*v1), math.hypot(*v2)
        if n1 == 0 or n2 == 0:
            continue
        cosine = abs((v1[0] * v2[0] + v1[1] * v2[1]) / (n1 * n2))
        skew = abs(n1 - n2) / max(n1, n2)
        score = cosine + skew
        if best is None or score < best[0]:
            best = (score, a, b, c, v1, v2)
    if best is None:
        return None
    _, tl, b, c, v1, v2 = best
    if v1[0] * v2[1] - v1[1] * v2[0] < 0:  # в системе с осью y вниз: по часовой стрелке от TR к BL
        b, c = c, b
    return tl, b, c


def decode_qr(gray: bytes, width: int, height: int) -> str | None:
    """Ищет в снимке QR-код и возвращает его текст (None — кода нет или он не читается)."""
    if len(gray) != width * height:
        raise ValueError("размер данных не совпадает с размерами изображения")
    scale = 1
    while max(width, height) // scale > 640:
        scale += 1
    if scale > 1:
        small_w, small_h = width // scale, height // scale
        gray = bytes(gray[(y * scale) * width + x * scale] for y in range(small_h) for x in range(small_w))
        width, height = small_w, small_h
    bw = binarize(gray, width, height)
    finders = find_finders(bw)
    if len(finders) < 3:
        return None
    finders.sort(key=lambda f: -f[2])
    tried = 0
    for i in range(len(finders)):
        for j in range(i + 1, len(finders)):
            for k in range(j + 1, len(finders)):
                triple = [finders[i], finders[j], finders[k]]
                units = [f[2] for f in triple]
                if max(units) > 1.6 * min(units):
                    continue
                ordered = _order([(f[0], f[1]) for f in triple])
                if ordered is None:
                    continue
                tl, tr, bl = ordered
                module = sum(units) / 3
                width_modules = math.hypot(tr[0] - tl[0], tr[1] - tl[1]) / module + 7
                estimate = round((width_modules - 17) / 4)
                for version in sorted({estimate, estimate - 1, estimate + 1}):
                    if not 1 <= version <= 10:
                        continue
                    dimension = 17 + 4 * version
                    text = decode_matrix(_grid(bw, tl, tr, bl, dimension))
                    if text is not None:
                        return text
                tried += 1
                if tried > 12:
                    return None
    return None
