import pytest
from backend.app.services.benchmarking_service import BenchmarkingService

def test_calculate_f1_perfect():
    service = BenchmarkingService()
    actual = {("Node A", "type1"), ("Node B", "type2")}
    reference = {("Node A", "type1"), ("Node B", "type2")}
    
    result = service.calculate_f1(actual, reference)
    assert result.f1 == 1.0
    assert result.tp == 2
    assert result.fp == 0
    assert result.fn == 0

def test_calculate_f1_partial():
    service = BenchmarkingService()
    # TP=1 (Node A), FP=1 (Node C), FN=1 (Node B)
    actual = {("Node A", "type1"), ("Node C", "type1")}
    reference = {("Node A", "type1"), ("Node B", "type1")}
    
    result = service.calculate_f1(actual, reference)
    # precision = 1/2, recall = 1/2 -> f1 = 0.5
    assert result.precision == 0.5
    assert result.recall == 0.5
    assert result.f1 == 0.5

def test_calculate_f1_empty():
    service = BenchmarkingService()
    result = service.calculate_f1(set(), set())
    assert result.f1 == 1.0

def test_calculate_f1_all_wrong():
    service = BenchmarkingService()
    actual = {("A", "T1")}
    reference = {("B", "T1")}
    result = service.calculate_f1(actual, reference)
    assert result.f1 == 0.0
    assert result.tp == 0
