import pytest
from calculator import add, multiply

def test_add():
    assert add(1, 2) == 3
    assert add(-1, -5) == -6
    assert add(0, 5) == 5
    assert add(10, -3) == 7

def test_multiply():
    assert multiply(2, 3) == 6
    assert multiply(-2, 4) == -8
    assert multiply(0, 5) == 0
    assert multiply(-3, -3) == 9
