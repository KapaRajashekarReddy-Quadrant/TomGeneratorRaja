# def next_position(index):
#     col = index % 2
#     row = index // 2

#     return {
#         "x": 50 + col * 650,
#         "y": 50 + row * 450
#     }


def next_position(index: int, x_start=40, y_start=40, row_height=340, col_width=650, max_per_row=2):
    row = index // max_per_row
    col = index % max_per_row
    x = x_start + col * col_width
    y = y_start + row * row_height
    return {"x": x, "y": y}
