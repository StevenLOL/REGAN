# -*- coding: utf-8 -*-
import copy
import torch
import torch.nn as nn
from torch.autograd import Variable
import numpy as np 

import utils


class NLLLoss(nn.Module):
    """Self-Defined NLLLoss Function

    Args:
        weight: Tensor (num_class, )
    """
    def __init__(self, weight):
        super(NLLLoss, self).__init__()
        self.weight = weight

    def forward(self, prob, target):
        """
        Args:
            prob: (N, C) 
            target : (N, )
        """
        N = target.size(0)
        C = prob.size(1)
        weight = Variable(self.weight).view((1, -1))
        weight = weight.expand(N, C)  # (N, C)
        if prob.is_cuda:
            weight = weight.cuda()
        prob = weight * prob

        one_hot = torch.zeros((N, C))
        if prob.is_cuda:
            one_hot = one_hot.cuda()
        one_hot.scatter_(1, target.data.view((-1,1)), 1)
        one_hot = one_hot.type(torch.ByteTensor)
        one_hot = Variable(one_hot)
        if prob.is_cuda:
            one_hot = one_hot.cuda()
        loss = torch.masked_select(prob, one_hot)
        return -torch.sum(loss)


class GANLoss(nn.Module):
    """Reward-Refined NLLLoss Function for adversial training of Gnerator"""
    def __init__(self):
        super(GANLoss, self).__init__()

    def forward_reinforce(self, prob, target, reward, cuda=False):
        """
        Args:
            prob: (N, C), torch Variable 
            target : (N, ), torch Variable
            reward : (N, ), torch Variable
        """
        N = target.size(0)
        C = prob.size(1)
        one_hot = torch.zeros((N, C))
        if cuda:
            one_hot = one_hot.cuda()
        one_hot.scatter_(1, target.data.view((-1,1)), 1)
        one_hot = one_hot.type(torch.ByteTensor)
        one_hot = Variable(one_hot)
        if cuda:
            one_hot = one_hot.cuda()
        loss = torch.masked_select(prob, one_hot)
        loss = loss * reward
        loss =  -torch.sum(loss)
        return loss
    
    def old_forward(self, GD, prob, target, reward, c_phi_hat, discriminator, BATCH_SIZE, g_sequence_len, cuda=False):
        """
        Forward function with implementation based on the original one.
        """
        N = target.size(0)
        C = prob.size(1)
        one_hot = torch.zeros((N, C))
        if cuda:
            one_hot = one_hot.cuda()
        one_hot.scatter_(1, target.data.view((-1,1)), 1)
        one_hot = one_hot.type(torch.ByteTensor)
        one_hot = Variable(one_hot)
        if cuda:
            one_hot = one_hot.cuda()
        loss = torch.masked_select(prob, one_hot)
        loss = loss.view(BATCH_SIZE, g_sequence_len)
        loss = torch.mean(loss, 1)
        c_phi_z, c_phi_z_tilde = utils.c_phi_out(GD, c_phi_hat, prob, discriminator, cuda)
        c_phi_z_tilde = c_phi_z_tilde[:,1]
        c_phi_z = c_phi_z[:,1]
        loss = loss * (reward - c_phi_z_tilde) + c_phi_z - c_phi_z_tilde
        loss =  - torch.sum(loss)
        return loss

    def forward(self, GD, prob, samples, reward, c_phi_hat, discriminator, BATCH_SIZE, g_sequence_len, VOCAB_SIZE, cuda=False):
        """
        Computes the Generator's loss in RELAX optimization setting. 

        """
        prob_temp = prob.view(BATCH_SIZE, g_sequence_len, VOCAB_SIZE)
        new_prob = Variable(torch.zeros(BATCH_SIZE, g_sequence_len))
        if cuda:
            new_prob = new_prob.cuda()
        for i in range(BATCH_SIZE):
            for j in range(g_sequence_len):
                new_prob[i,j] = prob_temp[i,j,int(samples[i,j])]
        loss = torch.sum(new_prob, 1)
        c_phi_z, c_phi_z_tilde = utils.c_phi_out(GD, c_phi_hat, prob, discriminator, cuda)
        c_phi_z_tilde = c_phi_z_tilde[:,1]
        c_phi_z = c_phi_z[:,1]
        loss = loss * (reward - c_phi_z_tilde) + c_phi_z - c_phi_z_tilde
        loss =  - torch.sum(loss)
        return loss

    def forward_reward(self, i, samples, prob, rewards, BATCH_SIZE, g_sequence_len, VOCAB_SIZE, cuda=False):
        """
        Computes the Generator's loss in RELAX optimization setting. 

        """
        conditional_proba = Variable(torch.zeros(BATCH_SIZE, VOCAB_SIZE))
        if cuda:
            conditional_proba = conditional_proba.cuda()
        for j in range(BATCH_SIZE):
            conditional_proba[j, int(samples[j, i])] = prob[j, i, int(samples[j, i])]
            conditional_proba[j, :] = -rewards[j] * conditional_proba[j, :]
        return conditional_proba

    def forward_reward_grads(self, samples, prob, rewards, g, BATCH_SIZE, g_sequence_len, VOCAB_SIZE, cuda=False):
        """
        Computes the Generator's loss in RELAX optimization setting. 

        """
        conditional_proba = Variable(torch.zeros(BATCH_SIZE, g_sequence_len, VOCAB_SIZE))
        batch_grads = []
        if cuda:
            conditional_proba = conditional_proba.cuda()
        for j in range(BATCH_SIZE):
            for i in range(g_sequence_len):
                conditional_proba[j, i, int(samples[j, i])] = prob[j, i, int(samples[j, i])]
            conditional_proba[j, :, :] = -rewards[j] * conditional_proba[j, :, :]
        last_idx = BATCH_SIZE-1
        for j in range(BATCH_SIZE):
            j_grads = []
            g.zero_grad()
            prob[j, :, :].backward(conditional_proba[j, :, :], retain_graph=True)
            for p in g.parameters():
                j_grads.append(p.grad)
            batch_grads.append(j_grads)
        return batch_grads

class VarianceLoss(nn.Module):
    """Loss for the control variate annex network"""
    def __init__(self):
        super(VarianceLoss, self).__init__()

    def forward(self, grad, cuda = False):
        bs = len(grad)
        total_loss = Variable(torch.zeros(1), requires_grad=True)
        if cuda:
            total_loss = total_loss.cuda()
        for j in range(bs):
            batch_j_loss = Variable(torch.zeros(1), requires_grad=True)
            if cuda:
                batch_j_loss = total_loss.cuda()
            for i in range(len(grad[j])):
                batch_j_loss = torch.add(batch_j_loss, torch.sum(grad[j][i]**2))
            total_loss = torch.add(total_loss, batch_j_loss)
        return total_loss/bs

