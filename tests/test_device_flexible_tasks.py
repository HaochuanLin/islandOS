import unittest
from islandos_core.flexible_tasks import DeviceTask, schedule_device_tasks

class DeviceTaskSchedulingTests(unittest.TestCase):
    def test_critical_load_reserved_first(self):
        critical = DeviceTask("clinic","Clinic","critical",5,10,0,4,interruptible=False,critical_power_profile_kw=(5,5,0,0))
        pump = DeviceTask("pump","Pump","fully_flexible",4,8,0,4)
        result = schedule_device_tasks([pump,critical],[.3,.1,.2,.05],[7,9,4,4])
        self.assertEqual(result.critical_power_kw,(5,5,0,0))
        self.assertEqual(result.schedules[1].power_kw,(0,0,0,4))
        self.assertLessEqual(max(result.total_power_kw),9)
    def test_fully_flexible_uses_cheapest_slots(self):
        task=DeviceTask("cold","Cold room","fully_flexible",2,4,0,4)
        result=schedule_device_tasks([task],[.4,.1,.3,.05],[2]*4)
        self.assertEqual(result.schedules[0].operating_steps,(1,3))
        self.assertAlmostEqual(result.total_energy_cost,.3)
    def test_semi_flexible_is_contiguous(self):
        task=DeviceTask("ice","Ice maker","semi_flexible",2,6,0,5,minimum_run_steps=2,interruptible=False)
        result=schedule_device_tasks([task],[.4,.1,.1,.3,.2],[2]*5)
        self.assertEqual(result.schedules[0].operating_steps,(1,2,3))
    def test_priority_applied_before_tariff(self):
        high=DeviceTask("high","High","fully_flexible",2,2,0,2,priority=1)
        low=DeviceTask("low","Low","fully_flexible",2,2,0,2,priority=10)
        result=schedule_device_tasks([low,high],[.1,.2],[2,2])
        self.assertEqual(result.schedules[0].task_id,"high")
        self.assertEqual(result.schedules[0].operating_steps,(0,))
        self.assertEqual(result.schedules[1].operating_steps,(1,))
    def test_infeasible_task_is_not_shed(self):
        task=DeviceTask("pump","Pump","fully_flexible",3,9,0,2)
        with self.assertRaisesRegex(ValueError,"infeasible"):
            schedule_device_tasks([task],[.1,.2],[3,3])
    def test_critical_capacity_violation_is_hard_error(self):
        task=DeviceTask("clinic","Clinic","critical",5,10,0,2,critical_power_profile_kw=(5,5))
        with self.assertRaisesRegex(ValueError,"critical load capacity violation"):
            schedule_device_tasks([task],[.1,.2],[4,5])
    def test_energy_quantum_is_explicit(self):
        task=DeviceTask("pump","Pump","fully_flexible",3,2,0,2)
        with self.assertRaisesRegex(ValueError,"integer multiple"):
            schedule_device_tasks([task],[.1,.2],[3,3])
    def test_window_and_availability_enforced(self):
        task=DeviceTask("pump","Pump","fully_flexible",2,2,1,4,availability=(True,False,True,True))
        result=schedule_device_tasks([task],[.01,.02,.3,.1],[2]*4)
        self.assertEqual(result.schedules[0].operating_steps,(3,))
    def test_invalid_window_rejected(self):
        task=DeviceTask("pump","Pump","fully_flexible",2,2,3,2)
        with self.assertRaisesRegex(ValueError,"operating window"):
            schedule_device_tasks([task],[.1]*4,[2]*4)
    def test_contiguous_task_respects_availability_at_every_step(self):
        task=DeviceTask("pump","Pump","semi_flexible",2,4,0,3,interruptible=False,availability=(True,False,True))
        with self.assertRaisesRegex(ValueError,"infeasible"):
            schedule_device_tasks([task],[.1,.2,.3],[2,2,2])
    def test_critical_profile_must_stay_inside_its_window(self):
        task=DeviceTask("clinic","Clinic","critical",5,10,0,1,critical_power_profile_kw=(5,5))
        with self.assertRaisesRegex(ValueError,"outside its operating window"):
            schedule_device_tasks([task],[.1,.2],[5,5])
    def test_interruptible_task_does_not_silently_ignore_minimum_run(self):
        task=DeviceTask("pump","Pump","fully_flexible",2,4,0,3,minimum_run_steps=2,interruptible=True)
        with self.assertRaisesRegex(ValueError,"minimum_run_steps=1"):
            schedule_device_tasks([task],[.1,.2,.3],[2,2,2])
    def test_energy_and_power_accounting(self):
        task=DeviceTask("pump","Pump","fully_flexible",2,4,0,3)
        result=schedule_device_tasks([task],[.1,.2,.3],[2,2,2],dt_hours=.5)
        self.assertAlmostEqual(result.schedules[0].energy_kwh,4)
        self.assertTrue(all(p<=c+1e-9 for p,c in zip(result.total_power_kw,[2,2,2])))

if __name__ == "__main__":
    unittest.main()
