import numpy as np
import pytest

from app.biometrics.face import pose as pose_lib
from app.biometrics.face.types import Pose


@pytest.mark.parametrize("yaw", [-40, -20, 0, 20, 40])
@pytest.mark.parametrize("pitch", [-25, 0, 25])
def test_estimated_pose_matches_the_true_pose(yaw, pitch):
    truth = Pose(yaw, pitch, 5)
    points = pose_lib.project_landmarks(truth, 640, 480, distance_mm=450)
    estimated = pose_lib.estimate_pose(points, 640, 480)
    assert estimated is not None
    assert estimated.yaw == pytest.approx(yaw, abs=2)
    assert estimated.pitch == pytest.approx(pitch, abs=2)
    assert estimated.roll == pytest.approx(5, abs=2)


def test_pose_estimation_tolerates_landmark_noise():
    rng = np.random.default_rng(0)
    for yaw in (-30, 0, 30):
        points = pose_lib.project_landmarks(Pose(yaw, 0, 0), 640, 480, distance_mm=450)
        noisy = points + rng.normal(0, 0.7, size=points.shape).astype(np.float32)
        estimated = pose_lib.estimate_pose(noisy, 640, 480)
        assert estimated.yaw == pytest.approx(yaw, abs=7)


def test_turning_opposite_ways_gives_opposite_signs():
    left = pose_lib.estimate_pose(pose_lib.project_landmarks(Pose(-25, 0, 0), 320, 240), 320, 240)
    right = pose_lib.estimate_pose(pose_lib.project_landmarks(Pose(25, 0, 0), 320, 240), 320, 240)
    assert left.yaw * right.yaw < 0


def test_pose_rules():
    front = Pose(0, 0, 0)
    codes = lambda name, pose, ref=front: [i.code for i in pose_lib.pose_issues(name, pose, ref)]  # noqa: E731
    assert codes("front", Pose(3, 2, 0), None) == []
    assert codes("front", Pose(40, 0, 0), None) == ["not_frontal"]
    assert codes("front", Pose(0, 0, 40), None) == ["tilted"]
    assert codes("left", Pose(-25, 0, 0)) == []
    assert codes("left", Pose(-4, 0, 0)) == ["turn_more"]
    assert codes("left", Pose(-25, 40, 0)) == ["keep_level"]
    assert codes("up", Pose(0, -15, 0)) == []
    assert codes("up", Pose(0, -2, 0)) == ["tilt_more"]
    assert codes("down", Pose(30, 15, 0)) == ["keep_straight"]
    assert codes("left", Pose(-25, 0, 0), None) == ["no_reference"]


def test_opposite_pose_rule():
    front = Pose(0, 0, 0)
    ok = {"left": Pose(-25, 0, 0), "right": Pose(25, 0, 0), "up": Pose(0, -15, 0), "down": Pose(0, 15, 0)}
    assert pose_lib.opposite_pose_issues(ok, front) == {}
    same = {**ok, "right": Pose(-25, 0, 0), "down": Pose(0, -15, 0)}
    assert set(pose_lib.opposite_pose_issues(same, front)) == {"right", "down"}
