import os
import csv
from collections import defaultdict

from tqdm import tqdm
from rdkit import Chem, RDLogger

import torch

from torchdrug import data, utils
from torchdrug.data import feature
from torchdrug.core import Registry as R
from torchdrug.utils import doc


@R.register("datasets.QM8")
@doc.copy_args(data.MoleculeDataset.load_csv, ignore=("smiles_field", "target_fields"))
class QM8(data.MoleculeDataset):
    """
    Electronic spectra and excited state energy of small molecules.

    Statistics:
        - #Molecule: 21,786
        - #Regression task: 12

    Parameters:
        path (str): path to store the dataset
        node_position (bool, optional): load node position or not.
            This will add `node_position` as a node attribute to each sample.
        verbose (int, optional): output verbose level
        **kwargs
    """

    url = "http://deepchem.io.s3-website-us-west-1.amazonaws.com/datasets/gdb8.tar.gz"
    md5 = "b7e2a2c823c75b35c596f3013319c86e"
    target_fields = ["E1-CC2", "E2-CC2", "f1-CC2", "f2-CC2",
                     "E1-PBE0/def2SVP", "E2-PBE0/def2SVP", "f1-PBE0/def2SVP", "f2-PBE0/def2SVP",
                     "E1-PBE0/def2TZVP", "E2-PBE0/def2TZVP", "f1-PBE0/def2TZVP", "f2-PBE0/def2TZVP",
                     "E1-CAM", "E2-CAM", "f1-CAM", "f2-CAM"]

    def __init__(self, path, node_position=False, verbose=1, **kwargs):
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            os.makedirs(path)
        self.path = path

        if not os.path.exists(os.path.join(self.path, os.path.basename(self.url))):
            zip_file = utils.download(self.url, self.path, md5=self.md5)
        else:
            zip_file = os.path.join(self.path, os.path.basename(self.url))

        sdf_file = utils.extract(zip_file, "qm8.sdf")
        csv_file = utils.extract(zip_file, "qm8.sdf.csv")
        csv_file2 = os.path.join(path, "qm8.sdf.clean.csv")

        if not os.path.exists(csv_file2):
            with open(csv_file, "r") as fin, open(csv_file2, "w") as fout:
                reader = csv.reader(fin)
                writer = csv.writer(fout)
                fields = next(reader)
                fields[5:9] = [field + "/def2SVP" for field in fields[5:9]]
                fields[9:13] = [field + "/def2TZVP" for field in fields[9:13]]
                writer.writerow(fields)
                for values in reader:
                    writer.writerow(values)

        self.load_csv(csv_file2, smiles_field=None, target_fields=self.target_fields, verbose=verbose)

        with utils.no_rdkit_log():
            molecules = Chem.SDMolSupplier(sdf_file, True, True, False)

        targets = self.targets
        self.data = []
        self.targets = defaultdict(list)
        assert len(molecules) == len(targets[self.target_fields[0]])
        indexes = range(len(molecules))
        if verbose:
            indexes = tqdm(indexes, "Constructing molecules from SDF")
        for i in indexes:
            with utils.capture_rdkit_log() as log:
                mol = molecules[i]
            if mol is None:
                continue
            d = data.Molecule.from_molecule(mol, **kwargs)
            if node_position:
                with d.node():
                    d.node_position = torch.tensor([feature.atom_position(atom) for atom in mol.GetAtoms()])
            self.data.append(d)
            for k in targets:
                self.targets[k].append(targets[k][i])
