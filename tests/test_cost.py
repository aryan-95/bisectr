from bisectr.cost import tasks_needed


def test_tasks_needed_exact():
    assert tasks_needed(1000, 0.001, 1.0, 0.6) == 2      # 1.0 / 0.6 -> 1.67 -> 2


def test_more_cpu_never_fewer_tasks():
    assert tasks_needed(500, 0.002, 1.0, 0.6) >= tasks_needed(500, 0.001, 1.0, 0.6)


def test_minimum_one_task():
    assert tasks_needed(1, 0.0001, 1.0, 0.6) == 1
