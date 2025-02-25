import os

from torchdrug import data, utils
from torchdrug.utils import doc
from torchdrug.core import Registry as R


@R.register("datasets.BACE")
@doc.copy_args(data.MoleculeDataset.load_csv, ignore=("smiles_field", "target_fields"))
class BACE(data.MoleculeDataset):
    r"""
    Binary binding results for a set of inhibitors of human :math:`\beta`-secretase 1(BACE-1).

    Statistics:
        - #Molecule: 1,513
        - #Classification task: 1

    Parameters:
        path (str): path to store the dataset
        verbose (int, optional): output verbose level
        **kwargs
    """

    url = "http://deepchem.io.s3-website-us-west-1.amazonaws.com/datasets/bace.csv"
    md5 = "ba7f8fa3fdf463a811fa7edea8c982c2"
    target_fields = ["Class"]

    def __init__(self, path, verbose=1, **kwargs):
        path = os.path.expanduser(path)
        if not os.path.exists(path):
            os.makedirs(path)
        self.path = path

        if not os.path.exists(os.path.join(self.path, os.path.basename(self.url))):
            file_name = utils.download(self.url, self.path, md5=self.md5)
        else:
            file_name = os.path.join(self.path, os.path.basename(self.url))

        self.load_csv(file_name, smiles_field="mol", target_fields=self.target_fields,
                      verbose=verbose, **kwargs)