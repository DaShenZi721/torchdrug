import os

from torchdrug import data, utils
from torchdrug.core import Registry as R
from torchdrug.utils import doc


@R.register("datasets.Lipophilicity")
@doc.copy_args(data.MoleculeDataset.load_csv, ignore=("smiles_field", "target_fields"))
class Lipophilicity(data.MoleculeDataset):
    """
    Experimental results of octanol/water distribution coefficient (logD at pH 7.4).

    Statistics:
        - #Molecule: 4,200
        - #Regression task: 1

    Parameters:
        path (str): path to store the dataset
        verbose (int, optional): output verbose level
        **kwargs
    """

    url = "http://deepchem.io.s3-website-us-west-1.amazonaws.com/datasets/Lipophilicity.csv"
    md5 = "85a0e1cb8b38b0dfc3f96ff47a57f0ab"
    target_fields = ["exp"]

    def __init__(self, path, verbose=1, **kwargs):
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            os.makedirs(path)
        self.path = path

        if not os.path.exists(os.path.join(self.path, os.path.basename(self.url))):
            file_name = utils.download(self.url, self.path, md5=self.md5)
        else:
            file_name = os.path.join(self.path, os.path.basename(self.url))

        self.load_csv(file_name, smiles_field="smiles", target_fields=self.target_fields,
                      verbose=verbose, **kwargs)
