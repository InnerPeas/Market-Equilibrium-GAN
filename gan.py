# -*- coding: utf-8 -*-
"""GAN.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1Ebm-51a0kHnpfvdnQ4-SVyEgejA-lIdl
"""

import json
import torch
import numpy as np
from tqdm import tqdm
import torch.optim as optim
import torch.nn as nn
import torch.nn.functional as F
import matplotlib.pyplot as plt
import pandas as pd
from scipy.integrate import solve_ivp
from datetime import datetime
import pytz, os

## Check if CUDA is available
train_on_gpu = torch.cuda.is_available()
torch.manual_seed(0)

if not train_on_gpu:
    print('CUDA is not available.  Training on CPU ...')
else:
    print('CUDA is available!  Training on GPU ...')

## Global Constants
S_VAL = 1 #245714618646 #1#

T = 252
TR = 1 #20
N_SAMPLE = 300 #128
ALPHA = 1 #1 #
BETA = 0.5
#GAMMA_BAR = 8.30864e-14 * S_VAL
#KAPPA = 2.

#GAMMA_1 = GAMMA_BAR*(KAPPA+1)/KAPPA
#GAMMA_2 = GAMMA_BAR*(KAPPA+1)

XI_LIST = torch.tensor([1, 2, -3]).float() / S_VAL # #torch.tensor([3, -3]).float()
GAMMA_LIST = torch.tensor([1, 1, 2]).float() #torch.tensor([1, 1]).float() #

S = 1
LAM = 0.1 #1.08102e-10/1 * S_VAL #0.1 #

S_TERMINAL = 1 #245.47
S_INITIAL = 0 #250 #0#

#BETA = GAMMA_BAR*S*ALPHA**2 + S_TERMINAL/TR

assert len(XI_LIST) == len(GAMMA_LIST) and torch.max(GAMMA_LIST) == GAMMA_LIST[-1]

GAMMA_BAR = 1 / torch.sum(1 / GAMMA_LIST)
GAMMA_MAX = torch.max(GAMMA_LIST)
N = len(XI_LIST)

## Setup Numpy Counterparts
GAMMA_LIST_NP = GAMMA_LIST.numpy().reshape((1, N))
XI_LIST_NP = XI_LIST.numpy().reshape((1, N))
GAMMA_BAR_NP = GAMMA_BAR.numpy()
GAMMA_MAX_NP = GAMMA_MAX.numpy()
###

## Setup Brownian Motion
dW_ST = torch.normal(0, np.sqrt(TR/T), size=(N_SAMPLE, T))
W_ST = torch.cumsum(torch.cat((torch.zeros((N_SAMPLE, 1)), dW_ST), dim=1), dim=1)

def InverseRiccati(t, R, LAM=LAM, GAMMA_BAR_NP=GAMMA_BAR_NP, GAMMA_LIST_NP=GAMMA_LIST_NP, GAMMA_MAX_NP=GAMMA_MAX_NP, ALPHA=ALPHA, N=N, XI_LIST_NP=XI_LIST_NP):
    RH = R[:N]
    RF = R[N:].reshape((N, N))
    
    const = (ALPHA + GAMMA_BAR_NP * np.sum((1 / GAMMA_LIST_NP[:,:-1] - 1 / GAMMA_MAX_NP) * RH[:-1]))
    dRH = np.zeros(N)
    dRF = np.zeros((N, N))
    for n in range(N - 1):
        ind = np.zeros(N)
        ind[n] = 1
        dRH[n] = np.sum((GAMMA_LIST_NP[:,:-1] * (N * ind[:-1] - 1) + GAMMA_MAX_NP) * XI_LIST_NP[:,:-1]) * const / N - np.matmul(RF[n,:-1], RH[:-1].reshape((N - 1, 1))) / LAM
    #dRH[-1] = -np.sum(dRH[:-1])
    for n in range(N - 1):
        for m in range(N - 1):
            ind = -1
            if n == m:
                ind += N
            dRF[n, m] = (GAMMA_LIST_NP[:, m] * ind + GAMMA_MAX_NP) * const ** 2 / N - np.matmul(RF[n,:-1], RF[:-1,m]) / LAM
#    if t == 0:
#        print(dRH, dRF)
    #dRH = (np.matmul(GAMMA_LIST_NP[:,:-1], N * np.identity(N - 1) - 1) + GAMMA_MAX_NP) * XI_LIST_NP[:,:-1] * const / N - np.matmul(RF[:,:-1], RH[:-1].reshape((N - 1, 1))) / LAM
    #dRF = (np.matmul(np.ones((N - 1, 1)), GAMMA_LIST_NP) * (N * np.identity(N) - 1)) * const ** 2 / N - np.matmul(RF[:,:-1], RF[:-1,:]) / LAM
    
    dR = np.hstack((dRH.reshape((-1,)), dRF.reshape((-1,))))
    return dR
    
R_0 = np.zeros(N * (N + 1))
time = np.linspace(0, TR, T)
res = solve_ivp(lambda t,R:InverseRiccati(t,R,LAM=LAM, GAMMA_BAR_NP=GAMMA_BAR_NP, GAMMA_LIST_NP=GAMMA_LIST_NP, GAMMA_MAX_NP=GAMMA_MAX_NP, ALPHA=ALPHA, N=N, XI_LIST_NP=XI_LIST_NP) , t_span=[0, TR], y0=R_0, t_eval=time)

RH = torch.tensor(res.y[:N])
RF = torch.tensor(res.y[N:])

F_exact, H_exact = RF.float(), RH.float()
F_exact = torch.flip(F_exact,[1])
H_exact = torch.flip(H_exact,[1])
#print(F_exact, H_exact)

SIGMA_T = ALPHA + GAMMA_BAR * (1 / GAMMA_LIST[:-1] - 1 / GAMMA_MAX).reshape((1, N - 1)) @ H_exact[:-1,:]
SIGMA_ST = torch.ones((N_SAMPLE, 1)) @ SIGMA_T.reshape((1, T))

def truth_psi(W_st_, cuda=False):
    psi_snt = torch.zeros((N_SAMPLE, N, T + 1))
    psi_dot_snt = torch.zeros((N_SAMPLE, N, T))
    ones = torch.ones((N_SAMPLE, 1)).float()
    if cuda:
        psi_snt = psi_snt.to(device="cuda")
        psi_dot_snt = psi_dot_snt.to(device="cuda")
        ones = ones.to(device="cuda")
    psi_snt[:,:,0] = S * GAMMA_BAR / GAMMA_LIST
    for t in range(T):
        psi_dot_snt[:,:-1,t] = -1 / LAM * ((psi_snt[:,:-1,t] - ones @ (GAMMA_BAR / GAMMA_LIST[:-1] * S).reshape((1, N - 1))) @ F_exact[:,t].reshape((N, N))[:-1,:-1].T + W_st_[:,t].reshape((N_SAMPLE, 1)) @ H_exact[:-1,t].reshape((1, N - 1)))
        psi_dot_snt[:,-1,t] = -torch.sum(psi_dot_snt[:,:-1,t], axis=1)
        psi_snt[:,:,t+1] = psi_snt[:,:,t] + psi_dot_snt[:,:,t] * TR / T
    return psi_snt

def get_mu_from_sigma(SIGMA_T, psi_snt, W_st_, is_T=False, cuda=False):
    if not is_T:
        T = psi_snt.shape[2]
        sigma_st = SIGMA_T.reshape((N_SAMPLE, 1)).cpu() @ torch.ones((1, T))
    else:
        T = psi_snt.shape[2] - 1
        sigma_st = torch.ones((N_SAMPLE, 1)) @ SIGMA_T.reshape((1, T))
    mu_st = torch.zeros((N_SAMPLE, T))
    if not is_T:
        if train_on_gpu:
            sigma_st = sigma_st.to(device="cuda")
            mu_st = mu_st.to(device="cuda")
        for n in range(N):
            mu_st += 1 / N * GAMMA_LIST[n] * sigma_st * (sigma_st * psi_snt.clone()[:,n,:] + XI_LIST[n] * W_st_)
    else:
        if cuda:
            sigma_st = sigma_st.to(device="cuda")
            mu_st = mu_st.to(device="cuda")
        for n in range(N):
            mu_st += 1 / N * GAMMA_LIST[n] * sigma_st * (sigma_st * psi_snt[:,n,1:] + XI_LIST[n] * W_st_[:,1:])
    return mu_st

PSI_SNT_TRUTH = truth_psi(W_ST)
PSI_SNT_TRUTH[:,-1,:] = S - torch.sum(PSI_SNT_TRUTH[:,:-1,:], axis=1)
MU_ST = get_mu_from_sigma(SIGMA_T, PSI_SNT_TRUTH, W_ST, is_T=True)
#print(PSI_SNT_TRUTH, MU_ST, SIGMA_T)

## Dump to Cuda
if train_on_gpu:
    XI_LIST = XI_LIST.to(device="cuda")
    GAMMA_LIST = GAMMA_LIST.to(device="cuda")
    GAMMA_BAR = GAMMA_BAR.to(device="cuda")
    GAMMA_MAX = GAMMA_MAX.to(device="cuda")
    SIGMA_ST = SIGMA_ST.to(device="cuda")
    MU_ST = MU_ST.to(device="cuda")
    W_ST = W_ST.to(device="cuda")
    dW_ST = dW_ST.to(device="cuda")
    PSI_SNT_TRUTH = PSI_SNT_TRUTH.to(device="cuda")
    F_exact = F_exact.to(device="cuda")
    H_exact = H_exact.to(device="cuda")

class S_0(nn.Module):
    def __init__(self):
        super(S_0, self).__init__()
        self.s_0 = nn.Linear(1, 1)
        torch.nn.init.constant_(self.s_0.weight, S_INITIAL)
  
    def forward(self, x):
        return self.s_0(x)

## Training
class Net(nn.Module):
    def __init__(self, INPUT_DIM, HIDDEN_DIM_LST, OUTPUT_DIM=1):
        super(Net, self).__init__()
        self.layer_lst = nn.ModuleList()
        self.bn = nn.ModuleList()

        self.layer_lst.append(nn.Linear(INPUT_DIM, HIDDEN_DIM_LST[0]))
        self.bn.append(nn.BatchNorm1d(HIDDEN_DIM_LST[0],momentum=0.1))
        for i in range(1, len(HIDDEN_DIM_LST)):
            self.layer_lst.append(nn.Linear(HIDDEN_DIM_LST[i - 1], HIDDEN_DIM_LST[i]))
            self.bn.append(nn.BatchNorm1d(HIDDEN_DIM_LST[i],momentum=0.1))
        self.layer_lst.append(nn.Linear(HIDDEN_DIM_LST[-1], OUTPUT_DIM))

    def forward(self, x):
        for i in range(len(self.layer_lst) - 1):
            x = self.layer_lst[i](x)
            x = self.bn[i](x)
            x = F.relu(x)
        return self.layer_lst[-1](x)

def prepare_model(input_dim, output_dim, hidden_lst, lr, decay, scheduler_step, N_models=T, pretrained_model=None, use_s0=False):
    if pretrained_model is None:
        model_list = nn.ModuleList() #[]
        #optimizer_list = []
        #scheduler_list = []
        for _ in range(N_models):
            model = Net(input_dim, hidden_lst, output_dim)
            if train_on_gpu:
                model = model.to(device="cuda")
            model_list.append(model)
            #opt = optim.SGD(model.parameters(), lr=lr)
            #optimizer_list.append(opt)
            #scheduler_list.append(optim.lr_scheduler.StepLR(opt, step_size=scheduler_step, gamma=decay))
        if use_s0:
            model = S_0()
            if train_on_gpu:
                model = model.to(device="cuda")
            model_list.append(model)
    else:
        model_list = pretrained_model
    optimizer = optim.RMSprop(model_list.parameters(), lr=lr)
    scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=scheduler_step, gamma=decay)
    return model_list, optimizer, scheduler

def generator(discriminator_func, gen_hidden_lst, gen_lr=1e-3, gen_epoch=100, gen_decay=1, gen_scheduler_step=100, generator_func=None):
    #torch.manual_seed(0)
    model_list, optimizer, scheduler = prepare_model(3, 1, gen_hidden_lst, gen_lr, gen_decay, gen_scheduler_step, N_models=(N - 1) * T, pretrained_model=generator_func)
    
    loss_arr = []
    dW_, W_ = None, None
    print("Training Generator...")
    for _ in tqdm(range(gen_epoch)):
#        for i in range(len(optimizer_list)):
#            optimizer_list[i].zero_grad()
        optimizer.zero_grad()
        
        psi_dot_SNT = torch.zeros((N_SAMPLE, N, T + 1))
        psi_SNT = torch.zeros((N_SAMPLE, N, T + 1))
        loss_ST = torch.zeros((N_SAMPLE, T))
        mu_st = torch.zeros((N_SAMPLE, T))
        sigma_st = torch.zeros((N_SAMPLE, T))
        xi_snt = torch.zeros((N_SAMPLE, N, T))
        dW_ = torch.normal(0, np.sqrt(TR/T), size=(N_SAMPLE, T))
        W_ = torch.cumsum(torch.cat((torch.zeros((N_SAMPLE, 1)), dW_), dim=1), dim=1)
        stock_st = torch.zeros((N_SAMPLE, T + 1))
        gamma_sn = torch.ones((N_SAMPLE, 1)) @ GAMMA_LIST.cpu().reshape((1, N))
        dummy_1 = torch.ones((N_SAMPLE, 1))
        loss = torch.zeros(1)
        if train_on_gpu:
            psi_dot_SNT = psi_dot_SNT.to(device="cuda")
            psi_SNT = psi_SNT.to(device="cuda")
            loss_ST = loss_ST.to(device="cuda")
            dW_ = dW_.to(device="cuda")
            W_ = W_.to(device="cuda")
            loss = loss.to(device="cuda")
            mu_st = mu_st.to(device="cuda")
            sigma_st = sigma_st.to(device="cuda")
            stock_st = stock_st.to(device="cuda")
            xi_snt = xi_snt.to(device="cuda")
            gamma_sn = gamma_sn.to(device="cuda")
            dummy_1 = dummy_1.to(device="cuda")
        psi_SNT[:,:,0] = S * GAMMA_BAR / GAMMA_LIST

        for n in range(N):
            xi_snt[:,n,:] = XI_LIST[n] * W_[:,1:]
        stock_st[:,0] = discriminator_func[-1](dummy_1).reshape((-1,)) #S_INITIAL
    
        for t in range(T):
            #sigma_sn = torch.zeros((N_SAMPLE, N))
            #for n in range(N):
            curr_t = torch.ones((N_SAMPLE, 1))
            if train_on_gpu:
                curr_t = curr_t.to(device="cuda")
                #x0 = torch.cat((psi_SNT[:,:,t].reshape((N_SAMPLE, N)), curr_t), dim=1).cuda()
                x0 = torch.cat((W_[:,t].reshape((N_SAMPLE, 1)), curr_t), dim=1).cuda()
                #sigma_sn = sigma_sn.to(device="cuda")
            else:
                #x0 = torch.cat((psi_SNT[:,:,t].reshape((N_SAMPLE, N)), curr_t), dim=1)
                x0 = torch.cat((W_[:,t].reshape((N_SAMPLE, 1)), curr_t), dim=1)
            sigma_s = torch.abs(discriminator_func[t](x0).reshape((-1,)))
            mu_s = get_mu_from_sigma(sigma_s.reshape((N_SAMPLE, 1)), psi_SNT[:,:,t].reshape((N_SAMPLE, N, 1)), W_[:,t].reshape((N_SAMPLE, 1)))
#             if t == 0:
#                 print(x0[:3,:])
#                 print(sigma_s, mu_s[0])
            sigma_st[:,t] = sigma_s
            mu_st[:,t] = mu_s.reshape((-1,)) #0.5#
            stock_st[:,t+1] = stock_st[:,t] + mu_st[:,t] * TR / T + sigma_st[:,t] * dW_[:,t]

            for n in range(N - 1):
                if train_on_gpu:
                    x = torch.cat((psi_SNT[:,n,t].reshape((N_SAMPLE, 1)), W_[:,t].reshape((N_SAMPLE, 1)), curr_t), dim=1).cuda()
                else:
                    x = torch.cat((psi_SNT[:,n,t].reshape((N_SAMPLE, 1)), W_[:,t].reshape((N_SAMPLE, 1)), curr_t), dim=1)
                psi_dot_SNT[:,n,t+1] = model_list[n * T + t](x).reshape((-1,))
                psi_SNT[:,n,t+1] = psi_dot_SNT[:,n,t+1] / T * TR + psi_SNT[:,n,t]
            psi_dot_SNT[:,-1,t+1] = -torch.sum(psi_dot_SNT[:,:-1,t+1], axis=1)
            psi_SNT[:,-1,t+1] = S - torch.sum(psi_SNT[:,:-1,t+1], axis=1)
                
        dummy_multiplier = 1 #1e9
        loss = 0#torch.mean(torch.square(stock_st[:,-1] - BETA * T - ALPHA * W_[:,-1])) * 0.1
        for n in range(N):
            loss += (torch.mean(-torch.sum(mu_st * psi_SNT[:,n,1:], 1) + GAMMA_LIST[n] / 2 * torch.sum((sigma_st * psi_SNT[:,n,1:] + xi_snt[:,n,:]) ** 2, 1) + 1 / 2 * torch.sum(LAM * psi_dot_SNT[:,n,:] ** 2, 1)) / T) / N * dummy_multiplier
        #print(psi_SNT)
        
        loss_arr.append(float(loss.data) / dummy_multiplier)
        #loss += torch.mean(torch.square(sigma_st))
        loss.backward()

        if torch.isnan(loss.data):
            break

#        for i in range(len(optimizer_list)):
#            optimizer_list[i].step()
#            scheduler_list[i].step()
        optimizer.step()
        scheduler.step()
    
    loss_truth = 0
    psi_snt_truth = truth_psi(W_, cuda=train_on_gpu)
    mu_st_truth = get_mu_from_sigma(SIGMA_T, psi_snt_truth, W_, is_T=True, cuda=train_on_gpu)
    PSI_DOT_SNT_TRUTH = torch.zeros((N_SAMPLE, N, T + 1))
    PSI_DOT_SNT_TRUTH[:,:,1:] = (psi_snt_truth[:,:,1:] - psi_snt_truth[:,:,:-1]) * T / TR
    if train_on_gpu:
        psi_snt_truth = psi_snt_truth.to(device="cuda")
        PSI_DOT_SNT_TRUTH = PSI_DOT_SNT_TRUTH.to(device="cuda")
    for n in range(N):
        loss_truth += (torch.mean(-torch.sum(mu_st_truth * psi_snt_truth[:,n,1:], 1) + GAMMA_LIST[n] / 2 * torch.sum((SIGMA_ST * psi_snt_truth[:,n,1:] + xi_snt[:,n,:]) ** 2, 1) + 1 / 2 * torch.sum(LAM * PSI_DOT_SNT_TRUTH[:,n,:] ** 2, 1)) / T) / N

    #print(PSI_SNT_TRUTH, psi_SNT)
    return model_list, loss_arr, loss_truth

def discriminator(generator_func, dis_hidden_lst, dis_lr=1e-3, dis_epoch=100, dis_loss=2, dis_decay=1, dis_scheduler_step=100, discriminator_func=None):
    #torch.manual_seed(0)
    model_list, optimizer, scheduler = prepare_model(1 + 1, 1, dis_hidden_lst, dis_lr, dis_decay, dis_scheduler_step, N_models=T, pretrained_model=discriminator_func, use_s0=True)
    
    loss_arr = []
    dW_, W_ = None, None
    print("Training Discriminator...")
    for epoch in tqdm(range(dis_epoch)):
#        for i in range(len(optimizer_list)):
#            optimizer_list[i].zero_grad()
        optimizer.zero_grad()
        
        psi_dot_SNT = torch.zeros((N_SAMPLE, N, T + 1))
        psi_SNT = torch.zeros((N_SAMPLE, N, T + 1))
        loss_ST = torch.zeros((N_SAMPLE, T))
        mu_st = torch.zeros((N_SAMPLE, T))
        sigma_st = torch.zeros((N_SAMPLE, T))
        xi_snt = torch.zeros((N_SAMPLE, N, T))
        dW_ = torch.normal(0, np.sqrt(TR/T), size=(N_SAMPLE, T))
        W_ = torch.cumsum(torch.cat((torch.zeros((N_SAMPLE, 1)), dW_), dim=1), dim=1)
        stock_st = torch.zeros((N_SAMPLE, T + 1))
        gamma_sn = torch.ones((N_SAMPLE, 1)) @ GAMMA_LIST.cpu().reshape((1, N))
        loss = torch.zeros(1)
        dummy_1 = torch.ones((N_SAMPLE, 1))
        if train_on_gpu:
            psi_dot_SNT = psi_dot_SNT.to(device="cuda")
            psi_SNT = psi_SNT.to(device="cuda")
            loss_ST = loss_ST.to(device="cuda")
            dW_ = dW_.to(device="cuda")
            W_ = W_.to(device="cuda")
            loss = loss.to(device="cuda")
            mu_st = mu_st.to(device="cuda")
            sigma_st = sigma_st.to(device="cuda")
            xi_snt = xi_snt.to(device="cuda")
            stock_st = stock_st.to(device="cuda")
            gamma_sn = gamma_sn.to(device="cuda")
            dummy_1 = dummy_1.to(device="cuda")
        psi_SNT[:,:,0] = S * GAMMA_BAR / GAMMA_LIST
        for n in range(N):
            xi_snt[:,n,:] = XI_LIST[n] * W_[:,1:]
        stock_st[:,0] = model_list[-1](dummy_1).reshape((-1,)) #S_INITIAL
        
        for t in range(T):
            #sigma_sn = torch.zeros((N_SAMPLE, N))
            #for n in range(N):
            curr_t = torch.ones((N_SAMPLE, 1))
            if train_on_gpu:
                curr_t = curr_t.to(device="cuda")
                #x0 = torch.cat((psi_SNT[:,:,t].reshape((N_SAMPLE, N)), curr_t), dim=1).cuda()
                x0 = torch.cat((W_[:,t].reshape((N_SAMPLE, 1)), curr_t), dim=1).cuda()
                #sigma_sn = sigma_sn.to(device="cuda")
            else:
                #x0 = torch.cat((psi_SNT[:,:,t].reshape((N_SAMPLE, N)), curr_t), dim=1)
                x0 = torch.cat((W_[:,t].reshape((N_SAMPLE, 1)), curr_t), dim=1)
            sigma_s = torch.abs(model_list[t](x0).reshape((-1,)))
            mu_s = get_mu_from_sigma(sigma_s.reshape((N_SAMPLE, 1)), psi_SNT[:,:,t].reshape((N_SAMPLE, N, 1)), W_[:,t].reshape((N_SAMPLE, 1)))
            sigma_st[:,t] = sigma_s
            mu_st[:,t] = mu_s.reshape((-1,))
            stock_st[:,t+1] = stock_st[:,t] + mu_st[:,t] * TR / T + sigma_st[:,t] * dW_[:,t]
            for n in range(N - 1):
                if train_on_gpu:
                    x = torch.cat((psi_SNT[:,n,t].reshape((N_SAMPLE, 1)), W_[:,t].reshape((N_SAMPLE, 1)), curr_t), dim=1).cuda()
                else:
                    x = torch.cat((psi_SNT[:,n,t].reshape((N_SAMPLE, 1)), W_[:,t].reshape((N_SAMPLE, 1)), curr_t), dim=1)
                psi_dot_SNT[:,n,t+1] = generator_func[n * T + t](x).reshape((-1,))
                psi_SNT[:,n,t+1] += psi_dot_SNT[:,n,t+1] / T * TR + psi_SNT[:,n,t]
            psi_dot_SNT[:,-1,t+1] = -torch.sum(psi_dot_SNT[:,:-1,t+1], axis=1)
            psi_SNT[:,-1,t+1] = S - torch.sum(psi_SNT[:,:-1,t+1], axis=1)
    
        loss = torch.mean(torch.abs(stock_st[:,-1] - BETA * TR - ALPHA * W_[:,-1]) ** dis_loss) * 1 #torch.mean(torch.square(torch.sum(psi_dot_SNT, axis=1)))
#         for n in range(N):
#             loss += (torch.mean(-torch.sum(mu_st * psi_SNT[:,n,1:], 1) + GAMMA_LIST[n] / 2 * torch.sum((sigma_st * psi_SNT[:,n,1:] + xi_snt[:,n,:]) ** 2, 1) + 1 / 2 * torch.sum(LAM * psi_dot_SNT[:,n,:] ** 2, 1)) / T) / N
        loss_arr.append(float(loss.data))
        #loss += torch.mean(torch.square(sigma_st - torch.mean(sigma_st)))
        loss.backward()

        if torch.isnan(loss.data):
            break

#        for i in range(len(optimizer_list)):
#            optimizer_list[i].step()
#            scheduler_list[i].step()
        optimizer.step()
        
        #if epoch in [50000, 100000]: #[1000, 5000, 10000]: #
        scheduler.step()

    loss_truth = 0
    psi_snt_truth = truth_psi(W_, cuda=train_on_gpu)
    mu_st_truth = get_mu_from_sigma(SIGMA_T, psi_snt_truth, W_, is_T=True, cuda=train_on_gpu)
    PSI_DOT_SNT_TRUTH = torch.zeros((N_SAMPLE, N, T + 1))
    PSI_DOT_SNT_TRUTH[:,:,1:] = (psi_snt_truth[:,:,1:] - psi_snt_truth[:,:,:-1]) * T / TR
    if train_on_gpu:
        psi_snt_truth = psi_snt_truth.to(device="cuda")
        PSI_DOT_SNT_TRUTH = PSI_DOT_SNT_TRUTH.to(device="cuda")
    for n in range(N):
        loss_truth += (torch.mean(-torch.sum(mu_st_truth * psi_snt_truth[:,n,1:], 1) + GAMMA_LIST[n] / 2 * torch.sum((SIGMA_ST * psi_snt_truth[:,n,1:] + xi_snt[:,n,:]) ** 2, 1) + 1 / 2 * torch.sum(LAM * PSI_DOT_SNT_TRUTH[:,n,:] ** 2, 1)) / T) / N

    return model_list, loss_arr, loss_truth

def moderator(gen_hidden_lst, dis_hidden_lst, gen_lr=[1e-3], gen_epoch=[100], gen_decay=1, gen_scheduler_step=100, dis_lr=[1e-3], dis_epoch=[100], dis_loss=[2], dis_decay=1, dis_scheduler_step=100, total_rounds=10, visualize_obs=0, train_gen = True, train_dis = True, use_pretrained_gen = False, use_pretrained_dis = False, last_round_dis=True):
    ## Initialize
    torch.manual_seed(2021)
    ts_lst = [f.strip(".pt").split("__")[1] for f in os.listdir("Models/") if f.endswith(".pt")]
    ts_lst = sorted(ts_lst, reverse=True)
    if len(ts_lst) > 0:
        ts = ts_lst[0]
        print(ts)
    else:
        ts = None
    if train_gen and not use_pretrained_gen:
        generator_func, _, _ = prepare_model(3, 1, gen_hidden_lst, gen_lr[0], gen_decay, gen_scheduler_step, N_models=(N - 1) * T)
    else:
        generator_func = torch.load(f"Models/Generator__{ts}.pt")
    if train_dis and not use_pretrained_dis:
        discriminator_func, _, _ = prepare_model(1 + 1, 1, dis_hidden_lst, dis_lr[0], dis_decay, dis_scheduler_step, N_models=T, use_s0=True)
    else:
        discriminator_func = torch.load(f"Models/Discriminator__{ts}.pt")
    
    curr_ts_lst = []
    
    ## Training
    for round in range(total_rounds):
        print("Round #" + str(round + 1) + ":")
        if train_gen:
            pretrained_model = None
            if use_pretrained_gen:
                pretrained_model = generator_func
            generator_func, loss_gen, loss_truth_gen = generator(discriminator_func, gen_hidden_lst, gen_lr[min(round, len(gen_lr) - 1)], gen_epoch[min(round, len(gen_epoch) - 1)], gen_decay, gen_scheduler_step, pretrained_model)
            visualize_loss(loss_gen, round + 1, "generator", loss_truth_gen)
        #if round < 2:
        if round == total_rounds - 1:
            train_dis = last_round_dis
        if train_dis:
            pretrained_model = None
            if use_pretrained_gen:
                pretrained_model = discriminator_func
            discriminator_func, loss_dis, loss_truth_dis = discriminator(generator_func, dis_hidden_lst, dis_lr[min(round, len(dis_lr) - 1)], dis_epoch[min(round, len(dis_epoch) - 1)], dis_loss[min(round, len(dis_loss) - 1)], dis_decay, dis_scheduler_step, pretrained_model)
            loss_truth_dis = 0
            visualize_loss(loss_dis, round + 1, "discriminator", loss_truth_dis)
    
        ## Getting Predictions
        psi_dot_SNT = torch.zeros((N_SAMPLE, N, T))
        psi_SNT = torch.zeros((N_SAMPLE, N, T + 1))
        loss_ST = torch.zeros((N_SAMPLE, T))
        mu_st = torch.zeros((N_SAMPLE, T))
        sigma_st = torch.zeros((N_SAMPLE, T))
        xi_snt = torch.zeros((N_SAMPLE, N, T))
        stock_st = torch.zeros((N_SAMPLE, T + 1))
        gamma_sn = torch.ones((N_SAMPLE, 1)) @ GAMMA_LIST.cpu().reshape((1, N))
        dummy_1 = torch.ones((N_SAMPLE, 1))
        loss = torch.zeros(1)
        if train_on_gpu:
            psi_dot_SNT = psi_dot_SNT.to(device="cuda")
            psi_SNT = psi_SNT.to(device="cuda")
            loss_ST = loss_ST.to(device="cuda")
            loss = loss.to(device="cuda")
            mu_st = mu_st.to(device="cuda")
            sigma_st = sigma_st.to(device="cuda")
            xi_snt = xi_snt.to(device="cuda")
            gamma_sn = gamma_sn.to(device="cuda")
            stock_st = stock_st.to(device="cuda")
            dummy_1 = dummy_1.to(device="cuda")
        for n in range(N):
            xi_snt[:,n,:] = XI_LIST[n] * W_ST[:,1:]
        psi_SNT[:,:,0] = S * GAMMA_BAR / GAMMA_LIST
        stock_st[:,0] = discriminator_func[-1](dummy_1).reshape((-1,)) #S_INITIAL

        for t in range(T):
            #sigma_sn = torch.zeros((N_SAMPLE, N))
            #for n in range(N):
            curr_t = torch.ones((N_SAMPLE, 1))
            if train_on_gpu:
                curr_t = curr_t.to(device="cuda")
                #x0 = torch.cat((psi_SNT[:,:,t].reshape((N_SAMPLE, N)), curr_t), dim=1).cuda()
                x0 = torch.cat((W_ST[:,t].reshape((N_SAMPLE, 1)), curr_t), dim=1).cuda()
                #sigma_sn = sigma_sn.to(device="cuda")
            else:
                #x0 = torch.cat((psi_SNT[:,:,t].reshape((N_SAMPLE, N)), curr_t), dim=1)
                x0 = torch.cat((W_ST[:,t].reshape((N_SAMPLE, 1)), curr_t), dim=1)
            sigma_s = torch.abs(discriminator_func[t](x0))#discriminator_func_truth(x0)#
            mu_s = get_mu_from_sigma(sigma_s, psi_SNT[:,:,t].reshape((N_SAMPLE, N, 1)), W_ST[:,t].reshape((N_SAMPLE, 1)))
            sigma_st[:,t] = sigma_s.reshape((-1,))
            mu_st[:,t] = mu_s.reshape((-1,))#0.5#
            stock_st[:,t+1] = stock_st[:,t] + mu_st[:,t] * TR / T + sigma_st[:,t] * dW_ST[:,t]
            for n in range(N - 1):
                if train_on_gpu:
                    x = torch.cat((psi_SNT[:,n,t].reshape((N_SAMPLE, 1)), W_ST[:,t].reshape((N_SAMPLE, 1)), curr_t), dim=1).cuda()
                else:
                    x = torch.cat((psi_SNT[:,n,t].reshape((N_SAMPLE, 1)), W_ST[:,t].reshape((N_SAMPLE, 1)), curr_t), dim=1)
                psi_dot_SNT[:,n,t] = generator_func[n * T + t](x).reshape((-1,))
                psi_SNT[:,n,t+1] += psi_dot_SNT[:,n,t] / T * TR + psi_SNT[:,n,t]
            psi_SNT[:,-1,t+1] = S - torch.sum(psi_SNT[:,:-1,t+1], axis=1)

        ## Visualization
        suffix = "_" + datetime.now(tz=pytz.timezone("America/New_York")).strftime("%Y-%m-%d-%H-%M")
        visualize_comparision(psi_SNT, mu_st, sigma_st, stock_st, visualize_obs, suffix)
        
        ## Checkpoint
        if round < total_rounds - 1:
            torch.save(generator_func, "Models/Generator_" + suffix + ".pt")
            torch.save(discriminator_func, "Models/Discriminator_" + suffix + ".pt")
            curr_ts_lst.append(suffix.replace("_", ""))
    
    return generator_func, discriminator_func, ts, curr_ts_lst

def discriminator_func_truth(x):
    ret = torch.ones(N_SAMPLE).reshape((N_SAMPLE, 1))
    if train_on_gpu:
        ret = ret.to(device="cuda")
    return ret

def generator_func_truth(x):
    return 0.5 * torch.ones(N_SAMPLE).reshape((N_SAMPLE, 1))

def visualize_loss(loss_arr, round, model, loss_truth):
    suffix = "_" + datetime.now(tz=pytz.timezone("America/New_York")).strftime("%Y-%m-%d-%H-%M")
    plt.plot(loss_arr)
    #plt.axhline(y=float(loss_truth), color="red")
    plt.xlabel("Epoch")
    plt.ylabel("Loss")
    plt.title("Loss at round #" + str(round) + " from " + model + "\nFinal Loss = " + str(loss_arr[-1]) + "\nGround Truth Loss = " + str(float(loss_truth)))
    plt.savefig("Plots/round=" + str(round) + "_model=" + model + suffix + ".png")
    plt.close()
    #plt.show()

def visualize_comparision(psi_SNT, mu_st, sigma_st, stock_st, visualize_obs, suffix):
    #suffix = "_" + datetime.now(tz=pytz.timezone("America/New_York")).strftime("%Y-%m-%d-%H-%M")
    ## Plot psi
    for n in range(N):
        time_stamps = 1 / T * np.arange(psi_SNT.shape[2]) * TR
        plt.plot(time_stamps, psi_SNT[visualize_obs,n,:].cpu().detach().numpy(), label="Estimated ${\\varphi}_t$ Agent " + str(n))
        time_stamps = 1 / T * np.arange(PSI_SNT_TRUTH.shape[2]) * TR
        plt.plot(time_stamps, PSI_SNT_TRUTH[visualize_obs,n,:].cpu().detach().numpy(), label="Ground Truth ${\\varphi}_t$ Agent " + str(n))
    plt.xlabel("T")
    plt.ylabel("${\\varphi}_t$")
    plt.title("${\\varphi}_t$")
    plt.legend()
    plt.savefig("Plots/psi_obs=" + str(visualize_obs) + suffix + ".png")
    plt.close()
    #plt.show()
    
    ## Plot psi dot
    psi_dot_snt = (psi_SNT[:,:,1:] - psi_SNT[:,:,:-1]) * T / TR
    psi_dot_truth = (PSI_SNT_TRUTH[:,:,1:] - PSI_SNT_TRUTH[:,:,:-1]) * T / TR
    for n in range(N):
        time_stamps = 1 / T * np.arange(psi_dot_snt.shape[2]) * TR
        plt.plot(time_stamps, psi_dot_snt[visualize_obs,n,:].cpu().detach().numpy(), label="Estimated $\dot{\\varphi}_t$ Agent " + str(n))
        time_stamps = 1 / T * np.arange(psi_dot_truth.shape[2]) * TR
        plt.plot(time_stamps, psi_dot_truth[visualize_obs,n,:].cpu().detach().numpy(), label="Ground Truth $\dot{\\varphi}_t$ Agent " + str(n))
    plt.xlabel("T")
    plt.ylabel("$\dot{\\varphi}_t$")
    plt.title("$\dot{\\varphi}_t$")
    #plt.ylim((-0.02, 0.02))
    plt.legend()
    plt.savefig("Plots/psi_dot_obs=" + str(visualize_obs) + suffix + ".png")
    plt.close()
    #plt.show()
    
    ## Plot stock
    time_stamps = 1 / T * np.arange(stock_st.shape[1]) * TR
    plt.plot(time_stamps, stock_st[visualize_obs,:].cpu().detach().numpy(), label="Estimated $S_t$")
    #plt.plot(BETA * 1/T * TR * np.arange(T+1) + ALPHA * W_ST[visualize_obs,:].detach().numpy(), label="Ground Truth $S_T$", color="red")
    plt.axhline(BETA * TR + ALPHA * W_ST[visualize_obs,-1], label="Ground Truth $S_T$", color="red")
    plt.xlabel("T")
    plt.ylabel("$S_t$")
    plt.title("$S_t$")
    plt.legend()
    plt.savefig("Plots/stock_obs=" + str(visualize_obs) + suffix + ".png")
    plt.close()
    #plt.show()
    
    ## Plot sigma
    #for n in range(N):
    time_stamps = 1 / T * np.arange(sigma_st.shape[1]) * TR
    plt.plot(time_stamps, sigma_st[visualize_obs,:].cpu().detach().numpy(), label="Estimated $\sigma_t$")
    time_stamps = 1 / T * np.arange(SIGMA_ST.shape[1]) * TR
    plt.plot(time_stamps, SIGMA_ST[visualize_obs,:].cpu().detach().numpy(), label="Ground Truth $\sigma_t$")
    plt.xlabel("T")
    plt.ylabel("$\sigma_t$")
    plt.title("$\sigma_t$")
    plt.legend()
    plt.savefig("Plots/sigma_obs=" + str(visualize_obs) + suffix + ".png")
    plt.close()
    #plt.show()
    
    ## Plot mu
    time_stamps = 1 / T * np.arange(mu_st.shape[1]) * TR
    plt.plot(time_stamps, mu_st[visualize_obs,:].cpu().detach().numpy(), label="Estimated $\mu_t$")
    time_stamps = 1 / T * np.arange(MU_ST.shape[1]) * TR
    plt.plot(time_stamps, MU_ST[visualize_obs,:].cpu().detach().numpy(), label="Ground Truth $\mu_t$")
    plt.xlabel("T")
    plt.ylabel("$\mu_t$")
    plt.title("$\mu_t$")
    plt.legend()
    plt.savefig("Plots/mu_obs=" + str(visualize_obs) + suffix + ".png")
    plt.close()
    #plt.show()

def write_logs(ts_lst, train_args):
    with open("Logs.tsv", "a") as f:
        for i in range(1, len(ts_lst)):
            line = f"{ts_lst[i - 1]}\t{ts_lst[i]}\t{json.dumps(train_args)}\n"
            f.write(line)
    
train_args = {"gen_hidden_lst": [50, 50, 50], "dis_hidden_lst": [50, 50, 50], "gen_lr": [1e-2, 1e-2, 1e-1, 1e-2, 1e-2, 1e-1], "gen_epoch": [100, 500, 1000, 5000, 10000], "gen_decay": 0.1, "gen_scheduler_step": 5000, "dis_lr": [1e-3, 1e-2, 1e-1, 1e-2], "dis_epoch": [10000, 500, 2000, 10000, 20000], "dis_loss": [1, 1, 1, 1], "dis_decay": 0.1, "dis_scheduler_step": 10000, "total_rounds": 1, "visualize_obs": 0, "train_gen": True, "train_dis": False, "use_pretrained_gen": True, "use_pretrained_dis": True, "last_round_dis": False}

generator_func, discriminator_func, prev_ts, curr_ts_lst = moderator(**train_args)

#generator_func, discriminator_func, prev_ts, curr_ts_lst = moderator(gen_hidden_lst = [50, 50, 50], dis_hidden_lst = [50, 50, 50], gen_lr=[1e-2, 1e-2, 1e-1, 1e-2, 1e-2, 1e-1], gen_epoch=[1000, 500, 1000, 5000, 10000], gen_decay=0.1, gen_scheduler_step=5000, dis_lr=[1e-3, 1e-2, 1e-1, 1e-2], dis_epoch=[10000, 500, 2000, 10000, 20000], dis_loss=[1, 1, 1, 1], dis_decay=0.1, dis_scheduler_step=10000, total_rounds=1, visualize_obs=0, train_gen=True, train_dis=False, use_pretrained_gen=True, use_pretrained_dis=True, last_round_dis=False)

suffix = "_" + datetime.now(tz=pytz.timezone("America/New_York")).strftime("%Y-%m-%d-%H-%M")
curr_ts_lst.append(suffix.replace("_", ""))
torch.save(generator_func, "Models/Generator_" + suffix + ".pt")
torch.save(discriminator_func, "Models/Discriminator_" + suffix + ".pt")

ts_lst = [prev_ts] + curr_ts_lst
write_logs(ts_lst, train_args)
# torch.save(generator_func, "Models/Generator.pt")
# torch.save(discriminator_func, "Models/Discriminator.pt")

