from __future__ import division # for proper float division

import os
import sys
import math
import time
import types
import functools
import random
import numpy as np
from director import ik
from director import ikconstraints
from director import ikconstraintencoder
import drc as lcmdrc
import json
from director.utime import getUtime
from director import lcmUtils


class PlannerPublisher(object):

  def __init__(self, ikPlanner, affordanceMan):
    self.ikPlanner = ikPlanner
    self.affordanceManager = affordanceMan
    self.poses={}

  def setupMessage(self, constraints, endPoseName="", nominalPoseName="", seedPoseName="", additionalTimeSamples=None):
    poses = ikconstraintencoder.getPlanPoses(constraints, self.ikPlanner)
    poses.update(self.poses)
    msg = lcmdrc.exotica_planner_request_t()
    msg.utime = getUtime()
    msg.poses = json.dumps(poses)
    msg.constraints = ikconstraintencoder.encodeConstraints(constraints)
    msg.seed_pose = seedPoseName
    msg.nominal_pose = nominalPoseName
    msg.end_pose = endPoseName
    msg.joint_names = json.dumps(list(self.ikPlanner.jointController.jointNames))
    msg.affordances = self.processAffordances()
    opt=ikplanner.getIkOptions()._properties
    if additionalTimeSamples:
      opt.update({'timeSamples':additionalTimeSamples})
    msg.options = json.dumps(opt)
    return msg

  def processIK(self, constraints, endPoseName="", nominalPoseName="", seedPoseName="", additionalTimeSamples=None):
    listener = self.ikPlanner.getManipIKListener()
    msg = self.setupMessage(constraints, endPoseName, nominalPoseName, seedPoseName, additionalTimeSamples)
    lcmUtils.publish('IK_REQUEST', msg)
    ikplan = listener.waitForResponse(timeout=12000)
    listener.finish()

    endPose = [0] * self.ikPlanner.jointController.numberOfJoints
    if ikplan.num_states>0:
      endPose[len(endPose)-len(ikplan.plan[ikplan.num_states-1].joint_position):] = ikplan.plan[ikplan.num_states-1].joint_position
      info=ikplan.plan_info[ikplan.num_states-1]
    else: 
      info = -1
    self.ikPlanner.ikServer.infoFunc(info)
    return endPose, info

  def processTraj(self, constraints, endPoseName="", nominalPoseName="", seedPoseName="", additionalTimeSamples=None):
    # Temporary fix / HACK / TODO (should be done in exotica_json)
    largestTspan = [0, 0]
    for constraintIndex, _ in enumerate(constraints):
      # Get tspan extend to normalise time-span
      if np.isfinite(constraints[constraintIndex].tspan[0]) and np.isfinite(constraints[constraintIndex].tspan[1]):
        largestTspan[0] = constraints[constraintIndex].tspan[0] if (constraints[constraintIndex].tspan[0] < largestTspan[0]) else largestTspan[0]
        largestTspan[1] = constraints[constraintIndex].tspan[1] if (constraints[constraintIndex].tspan[1] > largestTspan[1]) else largestTspan[1]

    # Temporary fix / HACK/ TODO to normalise time spans
    for constraintIndex, _ in enumerate(constraints):
      if np.isfinite(constraints[constraintIndex].tspan[0]) and np.isfinite(constraints[constraintIndex].tspan[1]):
        if largestTspan[1] != 0:
          constraints[constraintIndex].tspan[0] = constraints[constraintIndex].tspan[0] / largestTspan[1]
          constraints[constraintIndex].tspan[1] = constraints[constraintIndex].tspan[1] / largestTspan[1]

    listener = self.ikPlanner.getManipPlanListener()
    msg = self.setupMessage(constraints, endPoseName, nominalPoseName, seedPoseName, additionalTimeSamples)
    lcmUtils.publish('PLANNER_REQUEST', msg)
    lastManipPlan = listener.waitForResponse(timeout=20000)
    listener.finish()

    self.ikPlanner.ikServer.infoFunc(lastManipPlan.plan_info[0])
    return lastManipPlan, lastManipPlan.plan_info[0]

  def processAddPose(self, pose, poseName):
    self.poses[poseName]=list(pose);


  def processAffordances(self):
      affs = self.affordanceManager.getCollisionAffordances()
      s='['
      first=True
      for aff in affs:
        des=aff.getDescription()
        classname=des['classname'];
        if first:
          s+='{'
        else:
          s+='\n,{'
        first=False
        s+='"classname":"'+classname+'"'
        s+=',"name":"'+des['Name']+'"'
        s+=',"uuid":"'+des['uuid']+'"'
        s+=',"pose": {"position":{"__ndarray__":'+repr(des['pose'][0].tolist())+'},"quaternion":{"__ndarray__":'+repr(des['pose'][1].tolist())+'}}'
        if self.affordanceManager.affordanceUpdater is not None: # attached collision object / frameSync
          if des['Name'] in self.affordanceManager.affordanceUpdater.attachedAffordances:
            s+=',"attachedTo":"'+self.affordanceManager.affordanceUpdater.attachedAffordances[des['Name']]+'"'
          else: # it's not attached
            s+=',"attachedTo":"__world__"' # __world__ means it's a fixed collision object (sometimes called world or map - we use __world__ here)
        else: # no affordanceUpdater - so no attached collision objects either
          s+=',"attachedTo":"__world__"'
        if classname=='MeshAffordanceItem':
          s+=',"filename":"'+aff.getMeshManager().getFilesystemFilename(des['Filename'])+'"'
        if classname=='SphereAffordanceItem':
          s+=',"radius":'+repr(des['Radius'])
        if classname=='CylinderAffordanceItem' or classname=='CapsuleAffordanceItem':
          s+=',"radius":'+repr(des['Radius'])
          s+=',"length":'+repr(des['Length'])
        if classname=='BoxAffordanceItem':
          s+=',"dimensions":'+repr(des['Dimensions'])
        if classname=='CapsuleRingAffordanceItem':
          s+=',"radius":'+repr(des['Radius'])
          s+=',"tube_radius":'+repr(des['Tube Radius'])
          s+=',"segments":'+repr(des['Segments'])
        s+='}'
      s=s+']'
      return s

import ikplanner
