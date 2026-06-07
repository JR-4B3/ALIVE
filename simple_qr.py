from __future__ import annotations


VERSION = 4
SIZE = 17 + VERSION * 4
DATA_CODEWORDS = 80
EC_CODEWORDS = 20


def terminal_qr(text: str) -> str:
    modules = make_qr(text)
    quiet = 4
    dark = "\033[40m  \033[0m"
    light = "\033[47m  \033[0m"
    rows: list[str] = []
    width = len(modules) + quiet * 2
    rows.extend([light * width for _ in range(quiet)])
    for row in modules:
        line = []
        line.extend(light for _ in range(quiet))
        line.extend(dark if cell else light for cell in row)
        line.extend(light for _ in range(quiet))
        rows.append("".join(line))
    rows.extend([light * width for _ in range(quiet)])
    return "\n".join(rows)


def svg_qr(text: str, scale: int = 8) -> str:
    modules = make_qr(text)
    quiet = 4
    size = len(modules) + quiet * 2
    rects = []
    for y, row in enumerate(modules):
        for x, cell in enumerate(row):
            if cell:
                rects.append(
                    f'<rect x="{(x + quiet) * scale}" y="{(y + quiet) * scale}" '
                    f'width="{scale}" height="{scale}"/>'
                )
    px = size * scale
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {px} {px}" '
        f'width="{px}" height="{px}"><rect width="100%" height="100%" fill="#fff"/>'
        f'<g fill="#000">{"".join(rects)}</g></svg>'
    )


def make_qr(text: str) -> list[list[bool]]:
    data = text.encode("iso-8859-1")
    bits = _data_bits(data)
    codewords = [int(bits[i : i + 8], 2) for i in range(0, len(bits), 8)]
    codewords.extend(_reed_solomon_remainder(codewords, EC_CODEWORDS))
    stream = "".join(f"{value:08b}" for value in codewords)

    modules = [[False for _ in range(SIZE)] for _ in range(SIZE)]
    function = [[False for _ in range(SIZE)] for _ in range(SIZE)]
    _draw_function_patterns(modules, function)
    _draw_data(modules, function, stream)
    _apply_mask(modules, function)
    _draw_format_bits(modules, function, mask=0)
    return modules


def _data_bits(data: bytes) -> str:
    if len(data) > 78:
        raise ValueError("simple QR helper supports up to 78 bytes")
    bits = "0100" + f"{len(data):08b}" + "".join(f"{byte:08b}" for byte in data)
    bits += "0" * min(4, DATA_CODEWORDS * 8 - len(bits))
    bits += "0" * ((8 - len(bits) % 8) % 8)
    pads = [0xEC, 0x11]
    pad_index = 0
    while len(bits) < DATA_CODEWORDS * 8:
        bits += f"{pads[pad_index % 2]:08b}"
        pad_index += 1
    return bits


def _draw_function_patterns(modules: list[list[bool]], function: list[list[bool]]) -> None:
    _draw_finder(modules, function, 0, 0)
    _draw_finder(modules, function, SIZE - 7, 0)
    _draw_finder(modules, function, 0, SIZE - 7)
    for i in range(8, SIZE - 8):
        _set_function(modules, function, 6, i, i % 2 == 0)
        _set_function(modules, function, i, 6, i % 2 == 0)
    _draw_alignment(modules, function, 26, 26)
    _set_function(modules, function, 8, 4 * VERSION + 9, True)
    for i in range(9):
        if i != 6:
            _set_reserved(function, 8, i)
            _set_reserved(function, i, 8)
    for i in range(8):
        _set_reserved(function, 8, SIZE - 1 - i)
        _set_reserved(function, SIZE - 1 - i, 8)


def _draw_finder(
    modules: list[list[bool]], function: list[list[bool]], left: int, top: int
) -> None:
    for y in range(top - 1, top + 8):
        for x in range(left - 1, left + 8):
            if 0 <= x < SIZE and 0 <= y < SIZE:
                is_border = x in {left, left + 6} or y in {top, top + 6}
                is_center = left + 2 <= x <= left + 4 and top + 2 <= y <= top + 4
                _set_function(modules, function, x, y, is_border or is_center)


def _draw_alignment(
    modules: list[list[bool]], function: list[list[bool]], center_x: int, center_y: int
) -> None:
    for y in range(center_y - 2, center_y + 3):
        for x in range(center_x - 2, center_x + 3):
            value = max(abs(x - center_x), abs(y - center_y)) != 1
            _set_function(modules, function, x, y, value)


def _draw_data(
    modules: list[list[bool]], function: list[list[bool]], stream: str
) -> None:
    bit_index = 0
    direction = -1
    x = SIZE - 1
    while x > 0:
        if x == 6:
            x -= 1
        y_range = range(SIZE - 1, -1, -1) if direction == -1 else range(SIZE)
        for y in y_range:
            for dx in range(2):
                xx = x - dx
                if function[y][xx]:
                    continue
                modules[y][xx] = bit_index < len(stream) and stream[bit_index] == "1"
                bit_index += 1
        direction *= -1
        x -= 2


def _apply_mask(modules: list[list[bool]], function: list[list[bool]]) -> None:
    for y in range(SIZE):
        for x in range(SIZE):
            if not function[y][x] and (x + y) % 2 == 0:
                modules[y][x] = not modules[y][x]


def _draw_format_bits(
    modules: list[list[bool]], function: list[list[bool]], mask: int
) -> None:
    bits = _format_bits(mask)
    for i in range(6):
        _set_function(modules, function, 8, i, _bit(bits, i))
    _set_function(modules, function, 8, 7, _bit(bits, 6))
    _set_function(modules, function, 8, 8, _bit(bits, 7))
    _set_function(modules, function, 7, 8, _bit(bits, 8))
    for i in range(9, 15):
        _set_function(modules, function, 14 - i, 8, _bit(bits, i))
    for i in range(8):
        _set_function(modules, function, SIZE - 1 - i, 8, _bit(bits, i))
    for i in range(8, 15):
        _set_function(modules, function, 8, SIZE - 15 + i, _bit(bits, i))


def _format_bits(mask: int) -> int:
    data = (0b01 << 3) | mask
    value = data << 10
    generator = 0b10100110111
    for i in range(14, 9, -1):
        if (value >> i) & 1:
            value ^= generator << (i - 10)
    return ((data << 10) | value) ^ 0b101010000010010


def _bit(value: int, index: int) -> bool:
    return ((value >> index) & 1) != 0


def _set_function(
    modules: list[list[bool]], function: list[list[bool]], x: int, y: int, value: bool
) -> None:
    modules[y][x] = value
    function[y][x] = True


def _set_reserved(function: list[list[bool]], x: int, y: int) -> None:
    function[y][x] = True


def _reed_solomon_remainder(data: list[int], degree: int) -> list[int]:
    generator = _reed_solomon_generator(degree)
    result = [0] * degree
    for byte in data:
        factor = byte ^ result.pop(0)
        result.append(0)
        for i, coefficient in enumerate(generator):
            result[i] ^= _gf_multiply(coefficient, factor)
    return result


def _reed_solomon_generator(degree: int) -> list[int]:
    result = [1]
    for i in range(degree):
        result = _poly_multiply(result, [1, _gf_pow(2, i)])
    return result[1:]


def _poly_multiply(left: list[int], right: list[int]) -> list[int]:
    result = [0] * (len(left) + len(right) - 1)
    for i, left_value in enumerate(left):
        for j, right_value in enumerate(right):
            result[i + j] ^= _gf_multiply(left_value, right_value)
    return result


def _gf_pow(value: int, power: int) -> int:
    result = 1
    for _ in range(power):
        result = _gf_multiply(result, value)
    return result


def _gf_multiply(left: int, right: int) -> int:
    result = 0
    while right:
        if right & 1:
            result ^= left
        left <<= 1
        if left & 0x100:
            left ^= 0x11D
        right >>= 1
    return result
