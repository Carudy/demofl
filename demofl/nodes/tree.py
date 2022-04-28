from queue import Queue

from .raft import *
from ..aggregation import *


class TreeNode:
    def __init__(self, name, model, parent=None):
        self.max_m = 3
        self.name = str(name)
        self.parent = parent
        self.children = []
        self.model = model
        self.raft_node = RaftClient(name=self.name, owner=self)
        self.pos = 'leaf'
        self.comm_cnt = 0
        self.recv = {}
        self.params = self.model.get_parameters().copy()
        self.online = True

    def link(self, node):
        self.children.append(node)
        node.parent = self

    def learn_epoch(self, epoch):
        for c in self.children:
            c.learn_epoch(epoch)
        if self.children:
            group = [self] + self.children
            group_learn(group, epoch)


def group_learn(group, epoch):
    log(f'Group leader: {group[0].name} Learning epoch {group[0].model.epoch}')
    tds = []
    for c in group:
        if c.model.epoch <= epoch:
            c.model.set_parameters(group[0].params)
            td = threading.Thread(target=c.model.train_epoch)
            tds.append(td)
    log(f'{len(tds)} nodes need to learn.')
    for td in tds: td.start()
    for td in tds: td.join()

    for c in group:
        params = {
            k: secret_share(v * c.model.n_sample, 2)
            for k, v in c.model.get_parameters().items()
        }
        group[0].recv[int(c.name)] = {k: v[0] for k, v in params.items()}
        group[1].recv[int(c.name)] = {k: v[1] for k, v in params.items()}
    keys = list(group[0].recv.values())[0].keys()

    for i in range(2):
        a = []
        c = group[i]
        for v in c.recv.values():
            a.append(v.copy())
        c.params = fedadd(a)

    for k in keys:
        group[0].params[k] += group[1].params[k]

    group[0].model.n_sample += sum(c.model.n_sample for c in group[1:] if c.online)
    log(f'Done.')


def find_tree_p(root):
    q = Queue()
    q.put(root)
    while not q.empty():
        now = q.get()
        if len(now.children) < now.max_m:
            return now
        for c in now.children:
            q.put(c)
    return None


def make_tree(raft, root, others):
    others = [d for d in others if d.online]
    while others:
        p = find_tree_p(root)
        res = raft.elect_node([c.raft_node for c in others])
        c = 0
        while int(others[c].name) != res:
            c += 1
        p.link(others[c])
        log(f'{others[c].name} is selected, remain: {len(others)}')
        others = others[:c] + others[c + 1:]
        others = [d for d in others if d.online]
