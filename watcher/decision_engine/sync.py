# -*- encoding: utf-8 -*-
# Copyright (c) 2016 b<>com
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import collections

from oslo_log import log

from watcher._i18n import _LE, _LI
from watcher.common import context
from watcher.decision_engine.loading import default
from watcher import objects

LOG = log.getLogger(__name__)

GoalMapping = collections.namedtuple(
    'GoalMapping', ['name', 'display_name', 'efficacy_specification'])
StrategyMapping = collections.namedtuple(
    'StrategyMapping',
    ['name', 'goal_name', 'display_name', 'parameters_spec'])

IndicatorSpec = collections.namedtuple(
    'IndicatorSpec', ['name', 'description', 'unit', 'schema'])


class Syncer(object):
    """Syncs all available goals and strategies with the Watcher DB"""

    def __init__(self):
        self.ctx = context.make_context()
        self.discovered_map = None

        self._available_goals = None
        self._available_goals_map = None

        self._available_strategies = None
        self._available_strategies_map = None

        # This goal mapping maps stale goal IDs to the synced goal
        self.goal_mapping = dict()
        # This strategy mapping maps stale strategy IDs to the synced goal
        self.strategy_mapping = dict()

        self.stale_audit_templates_map = {}

    @property
    def available_goals(self):
        """Goals loaded from DB"""
        if self._available_goals is None:
            self._available_goals = objects.Goal.list(self.ctx)
        return self._available_goals

    @property
    def available_strategies(self):
        """Strategies loaded from DB"""
        if self._available_strategies is None:
            self._available_strategies = objects.Strategy.list(self.ctx)
        return self._available_strategies

    @property
    def available_goals_map(self):
        """Mapping of goals loaded from DB"""
        if self._available_goals_map is None:
            self._available_goals_map = {
                GoalMapping(
                    name=g.name,
                    display_name=g.display_name,
                    efficacy_specification=tuple(
                        IndicatorSpec(**item)
                        for item in g.efficacy_specification)): g
                for g in self.available_goals
            }
        return self._available_goals_map

    @property
    def available_strategies_map(self):
        if self._available_strategies_map is None:
            goals_map = {g.id: g.name for g in self.available_goals}
            self._available_strategies_map = {
                StrategyMapping(
                    name=s.name, goal_name=goals_map[s.goal_id],
                    display_name=s.display_name,
                    parameters_spec=str(s.parameters_spec)): s
                for s in self.available_strategies
            }
        return self._available_strategies_map

    def sync(self):
        self.discovered_map = self._discover()
        goals_map = self.discovered_map["goals"]
        strategies_map = self.discovered_map["strategies"]

        for goal_name, goal_map in goals_map.items():
            if goal_map in self.available_goals_map:
                LOG.info(_LI("Goal %s already exists"), goal_name)
                continue

            self.goal_mapping.update(self._sync_goal(goal_map))

        for strategy_name, strategy_map in strategies_map.items():
            if (strategy_map in self.available_strategies_map and
                    strategy_map.goal_name not in
                    [g.name for g in self.goal_mapping.values()]):
                LOG.info(_LI("Strategy %s already exists"), strategy_name)
                continue

            self.strategy_mapping.update(self._sync_strategy(strategy_map))

        self._sync_audit_templates()

    def _sync_goal(self, goal_map):
        goal_name = goal_map.name
        goal_mapping = dict()
        # Goals that are matching by name with the given discovered goal name
        matching_goals = [g for g in self.available_goals
                          if g.name == goal_name]
        stale_goals = self._soft_delete_stale_goals(goal_map, matching_goals)

        if stale_goals or not matching_goals:
            goal = objects.Goal(self.ctx)
            goal.name = goal_name
            goal.display_name = goal_map.display_name
            goal.efficacy_specification = [
                indicator._asdict()
                for indicator in goal_map.efficacy_specification]
            goal.create()
            LOG.info(_LI("Goal %s created"), goal_name)

            # Updating the internal states
            self.available_goals_map[goal] = goal_map
            # Map the old goal IDs to the new (equivalent) goal
            for matching_goal in matching_goals:
                goal_mapping[matching_goal.id] = goal

        return goal_mapping

    def _sync_strategy(self, strategy_map):
        strategy_name = strategy_map.name
        strategy_display_name = strategy_map.display_name
        goal_name = strategy_map.goal_name
        parameters_spec = strategy_map.parameters_spec
        strategy_mapping = dict()

        # Strategies that are matching by name with the given
        # discovered strategy name
        matching_strategies = [s for s in self.available_strategies
                               if s.name == strategy_name]
        stale_strategies = self._soft_delete_stale_strategies(
            strategy_map, matching_strategies)

        if stale_strategies or not matching_strategies:
            strategy = objects.Strategy(self.ctx)
            strategy.name = strategy_name
            strategy.display_name = strategy_display_name
            strategy.goal_id = objects.Goal.get_by_name(self.ctx, goal_name).id
            strategy.parameters_spec = parameters_spec
            strategy.create()
            LOG.info(_LI("Strategy %s created"), strategy_name)

            # Updating the internal states
            self.available_strategies_map[strategy] = strategy_map
            # Map the old strategy IDs to the new (equivalent) strategy
            for matching_strategy in matching_strategies:
                strategy_mapping[matching_strategy.id] = strategy

        return strategy_mapping

    def _sync_audit_templates(self):
        # First we find audit templates that are stale because their associated
        # goal or strategy has been modified and we update them in-memory
        self._find_stale_audit_templates_due_to_goal()
        self._find_stale_audit_templates_due_to_strategy()

        # Then we handle the case where an audit template became
        # stale because its related goal does not exist anymore.
        self._soft_delete_removed_goals()
        # Then we handle the case where an audit template became
        # stale because its related strategy does not exist anymore.
        self._soft_delete_removed_strategies()

        # Finally, we save into the DB the updated stale audit templates
        for stale_audit_template in self.stale_audit_templates_map.values():
            stale_audit_template.save()
            LOG.info(_LI("Audit Template '%s' synced"),
                     stale_audit_template.name)

    def _find_stale_audit_templates_due_to_goal(self):
        for goal_id, synced_goal in self.goal_mapping.items():
            filters = {"goal_id": goal_id}
            stale_audit_templates = objects.AuditTemplate.list(
                self.ctx, filters=filters)

            # Update the goal ID for the stale audit templates (w/o saving)
            for audit_template in stale_audit_templates:
                if audit_template.id not in self.stale_audit_templates_map:
                    audit_template.goal_id = synced_goal.id
                    self.stale_audit_templates_map[audit_template.id] = (
                        audit_template)
                else:
                    self.stale_audit_templates_map[
                        audit_template.id].goal_id = synced_goal.id

    def _find_stale_audit_templates_due_to_strategy(self):
        for strategy_id, synced_strategy in self.strategy_mapping.items():
            filters = {"strategy_id": strategy_id}
            stale_audit_templates = objects.AuditTemplate.list(
                self.ctx, filters=filters)

            # Update strategy IDs for all stale audit templates (w/o saving)
            for audit_template in stale_audit_templates:
                if audit_template.id not in self.stale_audit_templates_map:
                    audit_template.strategy_id = synced_strategy.id
                    self.stale_audit_templates_map[audit_template.id] = (
                        audit_template)
                else:
                    self.stale_audit_templates_map[
                        audit_template.id].strategy_id = synced_strategy.id

    def _soft_delete_removed_goals(self):
        removed_goals = [
            g for g in self.available_goals
            if g.name not in self.discovered_map['goals']]
        for removed_goal in removed_goals:
            removed_goal.soft_delete()
            filters = {"goal_id": removed_goal.id}
            invalid_ats = objects.AuditTemplate.list(self.ctx, filters=filters)
            for at in invalid_ats:
                LOG.warning(
                    _LE("Audit Template '%(audit_template)s' references a "
                        "goal that does not exist"),
                    audit_template=at.uuid)

    def _soft_delete_removed_strategies(self):
        removed_strategies = [
            s for s in self.available_strategies
            if s.name not in self.discovered_map['strategies']]

        for removed_strategy in removed_strategies:
            removed_strategy.soft_delete()
            filters = {"strategy_id": removed_strategy.id}
            invalid_ats = objects.AuditTemplate.list(self.ctx, filters=filters)
            for at in invalid_ats:
                LOG.info(
                    _LI("Audit Template '%(audit_template)s' references a "
                        "strategy that does not exist"),
                    audit_template=at.uuid)
                # In this case we can reset the strategy ID to None
                # so the audit template can still achieve the same goal
                # but with a different strategy
                if at.id not in self.stale_audit_templates_map:
                    at.strategy_id = None
                    self.stale_audit_templates_map[at.id] = at
                else:
                    self.stale_audit_templates_map[at.id].strategy_id = None

    def _discover(self):
        strategies_map = {}
        goals_map = {}
        discovered_map = {"goals": goals_map, "strategies": strategies_map}
        goal_loader = default.DefaultGoalLoader()
        implemented_goals = goal_loader.list_available()

        strategy_loader = default.DefaultStrategyLoader()
        implemented_strategies = strategy_loader.list_available()

        for _, goal_cls in implemented_goals.items():
            goals_map[goal_cls.get_name()] = GoalMapping(
                name=goal_cls.get_name(),
                display_name=goal_cls.get_translatable_display_name(),
                efficacy_specification=tuple(
                    IndicatorSpec(**indicator.to_dict())
                    for indicator in goal_cls.get_efficacy_specification(
                    ).get_indicators_specifications()))

        for _, strategy_cls in implemented_strategies.items():
            strategies_map[strategy_cls.get_name()] = StrategyMapping(
                name=strategy_cls.get_name(),
                goal_name=strategy_cls.get_goal_name(),
                display_name=strategy_cls.get_translatable_display_name(),
                parameters_spec=str(strategy_cls.get_schema()))

        return discovered_map

    def _soft_delete_stale_goals(self, goal_map, matching_goals):
        """Soft delete the stale goals

        :param goal_map: discovered goal map
        :type goal_map: :py:class:`~.GoalMapping` instance
        :param matching_goals: list of DB goals matching the goal_map
        :type matching_goals: list of :py:class:`~.objects.Goal` instances
        :returns: A list of soft deleted DB goals (subset of matching goals)
        :rtype: list of :py:class:`~.objects.Goal` instances
        """
        goal_display_name = goal_map.display_name
        goal_name = goal_map.name
        goal_efficacy_spec = goal_map.efficacy_specification

        stale_goals = []
        for matching_goal in matching_goals:
            if (matching_goal.efficacy_specification == goal_efficacy_spec and
                    matching_goal.display_name == goal_display_name):
                LOG.info(_LI("Goal %s unchanged"), goal_name)
            else:
                LOG.info(_LI("Goal %s modified"), goal_name)
                matching_goal.soft_delete()
                stale_goals.append(matching_goal)

        return stale_goals

    def _soft_delete_stale_strategies(self, strategy_map, matching_strategies):
        strategy_name = strategy_map.name
        strategy_display_name = strategy_map.display_name

        stale_strategies = []
        for matching_strategy in matching_strategies:
            if (matching_strategy.display_name == strategy_display_name and
                    matching_strategy.goal_id not in self.goal_mapping):
                LOG.info(_LI("Strategy %s unchanged"), strategy_name)
            else:
                LOG.info(_LI("Strategy %s modified"), strategy_name)
                matching_strategy.soft_delete()
                stale_strategies.append(matching_strategy)

        return stale_strategies
