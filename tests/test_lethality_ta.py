"""Lethality Fatality (passive) and Corrosive Return (skill-tree choice)."""

import heapq
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.swtorsim.config_load import load_from_run_config
from src.swtorsim.events import Event, PlayerReady
from src.swtorsim.run_config import load_run_config
from src.swtorsim.setup import prepare_simulation

RUN_CONFIG = ROOT / "data" / "run_config" / "Lethality.json"
FATALITY = "abl.agent.skill.lethality.fatality"
CORROSIVE_RETURN = "abl.agent.skill.lethality.mods.tier2.corrosive_return"
FINISHING_MOVE = "tag.abl.agent.finishing_move"
FATALITY_TAG = "tag.abl.agent.fatality"


class _Arrive(Event):
    def resolve(self, sim):
        return None


def _ta_stacks(player) -> int:
    for effect in player.effects.values():
        if getattr(effect, "is_expired", False):
            continue
        if FINISHING_MOVE in set(getattr(effect, "tags", ()) or ()):
            return int(getattr(effect, "stacks", 0) or 0)
    return 0


def _fatality_up(player) -> bool:
    for effect in player.effects.values():
        if getattr(effect, "is_expired", False):
            continue
        if FATALITY_TAG in set(getattr(effect, "tags", ()) or ()):
            return True
    return False


def _advance(sim, when: float) -> None:
    sim.schedule_absolute(when, _Arrive())
    sim.run_until(when)


class LethalityTacticalAdvantageTests(unittest.TestCase):
    """Fatality makes the next Corrosive Assault free and regrants a stack. Corrosive Return
    refunds the stack only when that cast would have left the player with none."""

    @classmethod
    def setUpClass(cls):
        cls._previous_cwd = Path.cwd()
        os.chdir(ROOT)

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls._previous_cwd)

    def _load(self, return_choice: int):
        config = load_run_config(str(RUN_CONFIG), environment="live")
        config.choices = dict(config.choices)
        config.choices["23"] = return_choice
        inputs = load_from_run_config(config)
        sim, player, target = prepare_simulation(
            {"steps": []},
            inputs.stats_config,
            inputs.loadout_blueprints,
            config.dummy_hp,
            inputs.debuff_module,
            verbose=False,
            seed=1,
            config=config,
            gcd_stall=0.0,
            pre_combat=[],
            precast="",
        )
        sim.queue = [item for item in sim.queue if not isinstance(item[2], PlayerReady)]
        heapq.heapify(sim.queue)
        return sim, player, target

    def test_fatality_and_corrosive_return(self):
        sim, player, target = self._load(1)
        self.assertIn(FATALITY, player.passive_db)
        self.assertIn(CORROSIVE_RETURN, player.passive_db)

        shiv = player.ability_db["shiv"]
        assault = player.ability_db["corrosive_assault"]
        self.assertTrue(shiv.cast(player, target, sim))
        self.assertEqual(_ta_stacks(player), 1)
        self.assertTrue(_fatality_up(player))
        fatality_lockout = sim.triggers.get_remaining_icd(FATALITY, sim.current_time)
        self.assertGreater(fatality_lockout, 6.0)

        _advance(sim, player.next_gcd)
        self.assertEqual(player.calculate_resource_cost(assault.name, assault.energy_cost), 0.0)
        energy_before = player.resource.current
        self.assertTrue(assault.cast(player, target, sim))
        self.assertEqual(player.resource.current, energy_before)
        self.assertFalse(_fatality_up(player))
        # The spend would have left zero, so Corrosive Return refunds immediately.
        self.assertEqual(_ta_stacks(player), 1)
        _advance(sim, sim.current_time + 0.25)
        # Fatality's regrant follows the 0.1s marker effect, after the return check.
        self.assertEqual(_ta_stacks(player), 2)

        # Shiv is ready before Fatality's lockout ends, and does not grant another Fatality.
        _advance(sim, player.cooldowns["Shiv"])
        self.assertGreater(sim.triggers.get_remaining_icd(FATALITY, sim.current_time), 0.0)
        self.assertTrue(shiv.cast(player, target, sim))
        self.assertFalse(_fatality_up(player))

        _advance(sim, sim.current_time + 10.0)
        self.assertEqual(sim.triggers.get_remaining_icd(CORROSIVE_RETURN, sim.current_time), 0.0)
        self.assertFalse(_fatality_up(player))
        self.assertEqual(_ta_stacks(player), 2)
        self.assertGreater(player.calculate_resource_cost(assault.name, assault.energy_cost), 0.0)
        self.assertTrue(assault.cast(player, target, sim))
        self.assertEqual(_ta_stacks(player), 1)
        _advance(sim, sim.current_time + 0.25)
        self.assertEqual(_ta_stacks(player), 1)

        _advance(sim, player.next_gcd)
        self.assertEqual(sim.triggers.get_remaining_icd(CORROSIVE_RETURN, sim.current_time), 0.0)
        self.assertEqual(_ta_stacks(player), 1)
        self.assertTrue(assault.cast(player, target, sim))
        self.assertEqual(_ta_stacks(player), 1)
        _advance(sim, sim.current_time + 0.25)
        self.assertEqual(_ta_stacks(player), 1)

    def test_without_corrosive_return_the_last_stack_is_spent(self):
        sim, player, target = self._load(2)
        self.assertIn(FATALITY, player.passive_db)
        self.assertNotIn(CORROSIVE_RETURN, player.passive_db)

        self.assertTrue(player.ability_db["shiv"].cast(player, target, sim))
        self.assertTrue(_fatality_up(player))
        # Fatality lasts 15s and ignores alacrity. Tactical Advantage lasts 24s.
        _advance(sim, 16.0)
        self.assertFalse(_fatality_up(player))
        self.assertEqual(_ta_stacks(player), 1)
        assault = player.ability_db["corrosive_assault"]
        self.assertGreater(player.calculate_resource_cost(assault.name, assault.energy_cost), 0.0)
        self.assertTrue(assault.cast(player, target, sim))
        self.assertEqual(_ta_stacks(player), 0)
        _advance(sim, sim.current_time + 0.25)
        self.assertEqual(_ta_stacks(player), 0)


if __name__ == "__main__":
    unittest.main()
