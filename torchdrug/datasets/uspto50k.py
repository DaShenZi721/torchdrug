import os
import copy
from collections import defaultdict

import numpy as np
import networkx as nx
from tqdm import tqdm
from rdkit import Chem

import torch
from torch.utils import data as torch_data
from torch_scatter import scatter_max

from torchdrug import data, utils
from torchdrug.utils import doc
from torchdrug.core import Registry as R


@R.register("datasets.USPTO50k")
@doc.copy_args(data.ReactionDataset.load_csv, ignore=("smiles_field", "target_fields"))
class USPTO50k(data.ReactionDataset):
    """
    Chemical reactions extracted from USPTO patents.

    Statistics:
        - #Reaction: 50,017
        - #Reaction class: 10

    Parameters:
        path (str): path to store the dataset
        as_synthon (bool, optional): whether decompose (reactant, product) pairs into (reactant, synthon) pairs
        verbose (int, optional): output verbose level
        **kwargs
    """

    target_fields = ["class"]
    target_alias = {"class": "reaction"}

    reaction_names = ["Heteroatom alkylation and arylation",
                      "Acylation and related processes",
                      "C-C bond formation",
                      "Heterocycle formation",
                      "Protections",
                      "Deprotections",
                      "Reductions",
                      "Oxidations",
                      "Functional group interconversion (FGI)",
                      "Functional group addition (FGA)"]

    url = "https://raw.githubusercontent.com/connorcoley/retrosim/master/retrosim/data/data_processed.csv"
    md5 = "404c361dd1568fbdb4d16ca588953749"

    def __init__(self, path, as_synthon=False, verbose=1, **kwargs):
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            os.makedirs(path)
        self.path = path
        self.as_synthon = as_synthon

        if not os.path.exists(os.path.join(self.path, os.path.basename(self.url))):
            file_name = utils.download(self.url, self.path, md5=self.md5)
        else:
            file_name = os.path.join(self.path, os.path.basename(self.url))

        self.load_csv(file_name, smiles_field="rxn_smiles", target_fields=self.target_fields, verbose=verbose,
                      **kwargs)

        if as_synthon:
            prefix = "Computing synthons"
            process_fn = self._get_synthon
        else:
            prefix = "Computing reaction centers"
            process_fn = self._get_reaction_center

        data = self.data
        targets = self.targets
        self.data = []
        self.targets = defaultdict(list)
        indexes = range(len(data))
        if verbose:
            indexes = tqdm(indexes, prefix)
        invalid = 0
        for i in indexes:
            reactant, product = data[i]

            reactants, products = process_fn(reactant, product)
            if not reactants:
                invalid += 1
                continue

            self.data += zip(reactants, products)
            for k in targets:
                new_k = self.target_alias.get(k, k)
                self.targets[new_k] += [targets[k][i] - 1] * len(reactants)
            self.targets["sample id"] += [i] * len(reactants)

        self.valid_rate = 1 - invalid / len(data)

    def _get_difference(self, reactant, product):
        product2id = product.atom_map
        id2reactant = torch.zeros(product2id.max() + 1, dtype=torch.long)
        id2reactant[reactant.atom_map] = torch.arange(reactant.num_node)
        prod2react = id2reactant[product2id]

        # check edges in the product
        edge_added = []
        edge_modified = []
        mask = product.edge_list[:, 0] < product.edge_list[:, 1]
        for h, t, r in product.edge_list[mask]:
            if (prod2react[h], prod2react[t]) not in reactant:
                edge_added.append((h, t))
            elif (prod2react[h], prod2react[t], r) not in reactant:
                edge_modified.append((h, t))

        return edge_added, edge_modified, prod2react

    def _get_reaction_center(self, reactant, product):
        edge_added, edge_modified, prod2react = self._get_difference(reactant, product)

        edge_label = torch.zeros(product.num_edge, dtype=torch.long)
        node_label = torch.zeros(product.num_node, dtype=torch.long)

        if edge_added:
            if len(edge_added) == 1: # add a single edge
                index = product.index(edge_added[0])
                assert len(index) == 1
                edge_label[index] = 1
                h, t = edge_added[0]
                reaction_center = torch.tensor([product.atom_map[h], product.atom_map[t]])
        else:
            if len(edge_modified) == 1: # modify a single edge
                h, t = edge_modified[0]
                if product.degree_in[h] == 1:
                    node_label[h] = 1
                    reaction_center = torch.tensor([product.atom_map[h], 0])
                elif product.degree_in[t] == 1:
                    node_label[t] = 1
                    reaction_center = torch.tensor([product.atom_map[t], 0])
                else:
                    # pretend the reaction center is h
                    node_label[h] = 1
                    reaction_center = torch.tensor([product.atom_map[h], 0])
            else:
                product_hs = torch.tensor([atom.GetTotalNumHs() for atom in product.to_molecule().GetAtoms()])
                reactant_hs = torch.tensor([atom.GetTotalNumHs() for atom in reactant.to_molecule().GetAtoms()])
                atom_modified = (product_hs != reactant_hs[prod2react]).nonzero().flatten()
                if len(atom_modified) == 1: # modify single node
                    node_label[atom_modified] = 1
                    reaction_center = torch.tensor([product.atom_map[atom_modified[0]], 0])

        if edge_label.sum() + node_label.sum() == 0:
            return [], []

        with product.edge():
            product.edge_label = edge_label
        with product.node():
            product.node_label = node_label
        with reactant.graph():
            reactant.reaction_center = reaction_center
        with product.graph():
            product.reaction_center = reaction_center
        return [reactant], [product]

    def _get_synthon(self, reactant, product):
        edge_added, edge_modified, prod2react = self._get_difference(reactant, product)

        reactants = []
        synthons = []

        if edge_added:
            if len(edge_added) == 1:  # add a single edge
                edge = edge_added[0]
                reverse_edge = edge[::-1]
                index = torch.cat([product.index(edge), product.index(reverse_edge)])
                edge_mask = torch.ones(product.num_edge, dtype=torch.bool)
                edge_mask[index] = 0
                product = product.edge_mask(edge_mask)
                _reactants = reactant.connected_components()[0]
                _synthons = product.connected_components()[0]
                assert len(_synthons) >= len(_reactants) # because a few samples contain multiple products

                h, t = edge
                reaction_center = torch.tensor([product.atom_map[h], product.atom_map[t]])
                with _reactants.graph():
                    _reactants.reaction_center = reaction_center.expand(len(_reactants), -1)
                with _synthons.graph():
                    _synthons.reaction_center = reaction_center.expand(len(_synthons), -1)
                # reactant / sython can be uniquely indexed by their maximal atom mapping ID
                reactant_id = scatter_max(_reactants.atom_map, _reactants.node2graph, dim_size=len(_reactants))[0]
                synthon_id = scatter_max(_synthons.atom_map, _synthons.node2graph, dim_size=len(_synthons))[0]
                react2synthon = (reactant_id.unsqueeze(-1) == synthon_id.unsqueeze(0)).long().argmax(-1)
                react2synthon = react2synthon.tolist()
                for r, s in enumerate(react2synthon):
                    reactants.append(_reactants[r])
                    synthons.append(_synthons[s])
        else:
            num_cc = reactant.connected_components()[1]
            assert num_cc == 1

            if len(edge_modified) == 1:  # modify a single edge
                synthon = product
                h, t = edge_modified[0]
                if product.degree_in[h] == 1:
                    reaction_center = torch.tensor([product.atom_map[h], 0])
                elif product.degree_in[t] == 1:
                    reaction_center = torch.tensor([product.atom_map[t], 0])
                else:
                    # pretend the reaction center is h
                    reaction_center = torch.tensor([product.atom_map[h], 0])
                with reactant.graph():
                    reactant.reaction_center = reaction_center
                with synthon.graph():
                    synthon.reaction_center = reaction_center
                reactants.append(reactant)
                synthons.append(synthon)
            else:
                product_hs = torch.tensor([atom.GetTotalNumHs() for atom in product.to_molecule().GetAtoms()])
                reactant_hs = torch.tensor([atom.GetTotalNumHs() for atom in reactant.to_molecule().GetAtoms()])
                atom_modified = (product_hs != reactant_hs[prod2react]).nonzero().flatten()
                if len(atom_modified) == 1:  # modify single node
                    synthon = product
                    reaction_center = torch.tensor([product.atom_map[atom_modified[0]], 0])
                    with reactant.graph():
                        reactant.reaction_center = reaction_center
                    with synthon.graph():
                        synthon.reaction_center = reaction_center
                    reactants.append(reactant)
                    synthons.append(synthon)

        return reactants, synthons

    def split(self, ratios=(0.8, 0.1, 0.1)):
        react2index = defaultdict(list)
        react2sample = defaultdict(list)
        for i in range(len(self)):
            reaction = self.targets["reaction"][i]
            sample_id = self.targets["sample id"][i]
            react2index[reaction].append(i)
            react2sample[reaction].append(sample_id)

        indexes = [[] for _ in ratios]
        for reaction in react2index:
            num_sample = len(set(react2sample[reaction]))
            key_lengths = [int(round(num_sample * ratio)) for ratio in ratios]
            key_lengths[-1] = num_sample - sum(key_lengths[:-1])
            react_indexes = data.key_split(react2index[reaction], react2sample[reaction], key_lengths=key_lengths)
            for index, react_index in zip(indexes, react_indexes):
                index += [i for i in react_index]

        return [torch_data.Subset(self, index) for index in indexes]

    @property
    def num_reaction_type(self):
        return len(self.reaction_types)

    @utils.cached_property
    def reaction_types(self):
        """All reaction types."""
        return sorted(set(self.target["class"]))