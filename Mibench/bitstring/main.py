from ast import Param
from email.contentmanager import raw_data_manager
from locale import normalize
import math
from operator import mod
from telnetlib import GA
from tkinter.tix import ListNoteBook
from turtle import color, forward, hideturtle
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from numpy import random
from torch.nn.parameter import Parameter
import dgl
import matplotlib.pyplot as plt
from matplotlib.ticker import MultipleLocator
import networkx as nx
import os
path1 = os.path.dirname(os.path.abspath(__file__))
from torch.utils.data import Dataset, DataLoader
import dgl.nn as dglnn

from utils import *
random_seed = 1388
np.random.seed(random_seed)
torch.manual_seed(random_seed)

edge_type = {1:'control', 2:'data', 3:'fun_call', 4:'load_store', 5:'jump'}



def noramlization(data):
    minVals = data.min(0)
    maxVals = data.max(0)
    ranges = maxVals - minVals
    #print(minVals, maxVals, ranges)
    normData = (data - minVals)/ranges
    return np.around(normData,4)

def to_hetero_feat(h, type, name):
    h_dict = {}
    for index, ntype in enumerate(name):
        h_dict[ntype] = h[torch.where(type == index)]

    return h_dict

import dgl.function as fn

class BBConv(nn.Module):
    def __init__(self, BB, hidden_size, h_size):
        super(BBConv, self).__init__()
        self.BB_numb = len(BB)
        self.BB = BB

    def forward(self, f):
        for i in range(self.BB_numb):
            h = f[self.BB[i]]
            h = torch.mean(h, dim = 0) 

        return 1


class HeteroRGCN(nn.Module):
    def __init__(self, BB_insize, BB_hidden, in_size, hidden_size, h_size,  out_size, BB_ins):
        super(HeteroRGCN, self).__init__()

        self.BBins = BB_ins 

        self.BBconv = dglnn.GraphConv(BB_insize, BB_hidden, norm= 'both', weight = True, bias = True, allow_zero_in_degree = True )
       

        self.Hgtconv = dglnn.HGTConv(in_size+BB_hidden, hidden_size, 2, 1, 5)

        self.dense = nn.Linear(2*hidden_size, out_size)
        self.dropout = nn.Dropout(p = 0.15)


        nn.init.uniform_(self.dense.weight, a=-0.1, b =0.1)
        nn.init.constant_(self.dense.bias, 0.1)

    def forward(self, G, BB_G, f, BB_f):

        res = self.BBconv(BB_G, BB_f)

        feature = f['node'] 
        ins_number = len(feature)
        temp = [[]]*ins_number

        for i in range(len(self.BBins)):

            temp[i] =res[int(self.BBins[i])].detach().numpy()

        temp = torch.FloatTensor(np.array(temp)) 

        temp = torch.cat([feature, temp], dim = 1)
        with G.local_scope():
            G.ndata['h'] = temp
            g = dgl.to_homogeneous(G, ndata='h')
            h = g.ndata['h']
            h,_ = self.Hgtconv(g, h, g.ndata['_TYPE'], g.edata['_TYPE'], presorted = True)
            h = F.leaky_relu(h)

            h = self.dense(h)
        h_dict = to_hetero_feat(h, g.ndata['_TYPE'], G.ntypes)

        return h_dict


def evaluate(model, graph, features, labels, index, BB_G, bb_features):
     model.eval()
     with torch.no_grad():
        logits = model(graph, BB_G, features, bb_features)
        logits = logits['node'][index]
        labels = labels[index]
        loss = F.cross_entropy(logits, labels)
        pred = logits.argmax(dim =1)
        true = labels.argmax(dim =1)
        e = 0.0000001
        TP, TN, FP, FN = 0, 0, 0, 0
        for i in range(pred.shape[0]):
            if pred[i] == 0 and true[i] == 0:
                TP += 1
            if pred[i] == 1 and true[i] == 1:
                TN += 1
            if pred[i] == 0 and true[i] == 1:
                FP += 1
            if pred[i] == 1 and true[i] == 0:
                FN += 1

        P = TP/(TP + FP + e)
        R = TP/(TP + FN + e)
        F1 = (2 * P * R)/(P + R + e)

        acc = torch.sum(pred == true).item() * 1.0 / len(index)

        return  loss, acc, P, F1

import random
random.seed(2)
def train_model(train_data_node, train_data_edge, BB_info, features, labels, args):


    device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
    BB_ins = features[:, 5]

    features = np.asarray(features, float) 

    for i in range(features.shape[1]):
        features[ :, i] = noramlization(features[:, i])

    features = torch.FloatTensor(features).to(device) 

    features = np.delete(features, [5,6], axis = 1)

    labels = np.asarray(labels, float)

    TS = 0
    T_index = [] 
    F_index = [] 
    FS = 0
    final_labels = [0]*len(labels)
    for i in range(len(labels)):
        if labels[i] >= 0.25: 
            final_labels[i] = [1,0]
            T_index.append(i) 
            TS += 1

        elif labels[i] > -1:
            final_labels[i] = [0,1]
            F_index.append(i)
            FS += 1
        else:
            final_labels[i] = [0,0]


    index = []
    test_index = []
    for i in range(len(labels)):
        if labels[i] != -1:
            index.append(i)
        else:
            test_index.append(i)
    T_train = random.sample(T_index, int(len(T_index)* args.split))
    F_train = random.sample(F_index, int(len(F_index)* args.split))
    idx_train = T_train + F_train
    random.shuffle(idx_train)
    idx_train = torch.LongTensor(idx_train)

    #Test Set: 
    idx_test = list((set(T_index) - set(T_train))) + list((set(F_index) - set(F_train)))
    random.shuffle(idx_test)
    
    #Validation Set, 20% of Test set
    idx_val = idx_test[0:int(len(idx_test)*0.2)]
    for i in range(len(idx_val)):
        idx_test.remove(idx_val[i]) #Remove validation set from test set

    idx_test = torch.LongTensor(idx_test)
    idx_val = torch.LongTensor(idx_val)

    labels = torch.FloatTensor(np.asarray(final_labels, float)).to(device)

    graph = dict()
    keys = list(train_data_edge.keys())
    for i in range(len(keys)):
        value = train_data_edge[keys[i]]
        str1 = list()
        str1.append('node')
        str1.append(edge_type[keys[i]])
        str1.append('node')
        head = [] 
        tail = [] 
        for j in range(len(value)):
            head.append(int(value[j][0]))
            tail.append(int(value[j][1]))
        graph[tuple(str1)]= (head, tail)

    G = dgl.heterograph(graph) 

    bb_nodes, bb_features, bb_edge = BB_info 
    bb_features = np.asarray(bb_features, float)    

    for i in range(bb_features.shape[1]):
        bb_features[ :, i] = noramlization(bb_features[:, i])

    bb_features = torch.FloatTensor(bb_features).to(device) 

    head = []
    tail = []
    for i in range(len(bb_edge)):
        head.append(int(bb_edge[i][0]))
        tail.append(int(bb_edge[i][1]))
    BB_G = dgl.graph((head, tail))
    


    feature = {}
    feature['node'] = features
    model = HeteroRGCN(3, 2, 5, 1, 5, 2, BB_ins).to(device)
    lossF = nn.MSELoss()
    
    opt = torch.optim.Adam(model.parameters(), lr=0.01, weight_decay=5e-4)
    best_val_acc = 0
    best_test_acc = 0
    model.train()
    loss_all = []
    dataset = DataLoader(idx_train, batch_size=64, shuffle=True)
    best_Acc = 0

    for epoch in range(3000):

            opt.zero_grad()
            logits = model(G, BB_G, feature, bb_features)
            logits = logits['node']

            loss = F.cross_entropy(logits[idx_train], labels[idx_train]) 
            pred = logits.argmax(dim =1)
            true = labels.argmax(dim =1)

            acc = torch.sum(pred[idx_train] == true[idx_train]).item() * 1.0 / len(idx_train)
            loss.backward()
            opt.step()
            loss_all.append(loss)

            if epoch % 5 == 0:
                val_loss, val_acc, val_P, val_F1 = evaluate(model, G, feature, labels, idx_val, BB_G, bb_features)
                if epoch < 1000:
                    continue
                elif val_acc >= best_Acc:
                    best_Acc = val_acc
                    torch.save(model, path1+ '\\model.pkl')    
    best_model = torch.load(path1+ '\\model.pkl')

    best_model.eval()
    with torch.no_grad():
        logits = best_model(G, BB_G, feature, bb_features)
        logits = logits['node'][idx_test]
        label_val = labels[idx_test]
        pred = logits.argmax(dim =1)
        true = label_val.argmax(dim =1)
        TP, TN, FP, FN = 0, 0, 0, 0
        e = 0.00000001
        for i in range(pred.shape[0]):
            if pred[i] == 0 and true[i] == 0:
                TP += 1
            if pred[i] == 1 and true[i] == 1:
                TN += 1
            if pred[i] == 0 and true[i] == 1:
                FP += 1
            if pred[i] == 1 and true[i] == 0:
                FN += 1
        P = TP/(TP + FP+ e)
        R = TP/(TP + FN+ e)
        F1 = (2 * P * R)/(P + R +e)
        acc = torch.sum(pred == true).item() * 1.0 / len(idx_test)
        print('test_ACC %.4f, test_Pre %.4f, test_F1 %.4f' % (
                    acc,
                    P,
                    F1,
            ))

    return












if __name__ == '__main__':
    args = parse_args()

    features , labels = load_feature_data()

    train_data_node , train_data_edge = load_train_data()

    BB_info = load_BB_info()

    train_model(train_data_node, train_data_edge, BB_info, features, labels, args)






