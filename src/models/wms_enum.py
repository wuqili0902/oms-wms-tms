"""WMS enums."""
from enum import Enum


class StockInType(Enum):
    """入库类型"""

    PURCHASE = "PURCHASE"         # 采购入库
    RETURN = "RETURN"            # 退货入库
    TRANSFER_IN = "TRANSFER_IN"  # 调拨入库
    ADJUSTMENT = "ADJUSTMENT"    # 调整入库


class StockOutType(Enum):
    """出库类型"""

    SALE = "SALE"             # 销售出库
    TRANSFER_OUT = "TRANSFER_OUT"   # 调拨出库
    ADJUSTMENT = "ADJUSTMENT"       # 调整出库


class AdjustReason(Enum):
    """盘盈盘亏原因"""

    DAMAGE = "DAMAGE"                    # 破损
    EXPIRED = "EXPIRED"                  # 过期
    LOST = "LOST"                        # 丢失
    FOUND = "FOUND"                      # 盘点找货
    COUNT_ERROR = "COUNT_ERROR"          # 盘点错误
