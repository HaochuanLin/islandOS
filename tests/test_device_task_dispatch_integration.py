import unittest
from islandos_core.energy_system import EnergySystemConfig, EnergySystemInputs, dispatch_energy_system
from islandos_core.flexible_tasks import DeviceTask, schedule_device_tasks
from islandos_core.flexible_task_dispatch import attach_device_task_schedule

class DeviceTaskDispatchIntegrationTests(unittest.TestCase):
    def test_task_profiles_flow_into_shared_energy_balance(self):
        clinic=DeviceTask("clinic","Clinic","critical",2,2,0,2,interruptible=False,critical_power_profile_kw=(2,0))
        pump=DeviceTask("pump","Pump","fully_flexible",2,2,0,2)
        task_schedule=schedule_device_tasks([clinic,pump],[.2,.1],[2,2])
        inputs=EnergySystemInputs(
            pv_generation_kw=[5,5], wind_generation_kw=[0,0],
            load_kw=[1,1], grid_price_per_kwh=[.2,.2], grid_available=[True,True],
        )
        integrated=attach_device_task_schedule(inputs,task_schedule)
        self.assertEqual(integrated.load_kw,[3.0,1.0])
        self.assertEqual(integrated.critical_load_kw,[3.0,1.0])
        self.assertEqual(integrated.flexible_load_kw,[0.0,2.0])
        result=dispatch_energy_system(integrated,EnergySystemConfig(
            pv_rated_kw=5,wind_rated_kw=0,grid_import_limit_kw=0,
        ))
        self.assertEqual(result["summary"]["critical_unmet_load_kwh"],0)
        self.assertEqual(result["summary"]["flexible_load_shed_kwh"],0)
        self.assertEqual(result["summary"]["unmet_load_kwh"],0)
        self.assertTrue(all(abs(row["energy_balance_residual_kw"])<1e-8 for row in result["rows"]))
    def test_horizon_mismatch_is_rejected(self):
        inputs=EnergySystemInputs([1],[0],[1],[.1],[True])
        schedule=schedule_device_tasks([], [.1,.2], [1,1])
        with self.assertRaisesRegex(ValueError,"match the energy input horizon"):
            attach_device_task_schedule(inputs,schedule)

if __name__=="__main__":
    unittest.main()
