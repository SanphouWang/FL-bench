from argparse import ArgumentParser, Namespace
from copy import deepcopy

from fedavg import FedAvgServer, get_fedavg_argparser
from src.client.fedsr import FedSRClient


def get_fedsr_argparser() -> ArgumentParser:
    parser = get_fedavg_argparser()
    parser.add_argument("--L2R_coeff", type=float, default=1e-2)
    parser.add_argument("--CMI_coeff", type=float, default=5e-4)
    return parser


class FedSRServer(FedAvgServer):
    def __init__(
        self,
        algo: str = "FedSR",
        args: Namespace = None,
        unique_model=False,
        default_trainer=False,
    ):
        if args is None:
            args = get_fedsr_argparser().parse_args()
        if "mobile" not in args.model and "res" not in args.model:
            raise NotImplementedError("Only support MobileNet and ResNet now")
        args.model = "_".join(["fedsr", args.model])
        super().__init__(algo, args, unique_model, default_trainer)
        self.trainer = FedSRClient(
            deepcopy(self.model), self.args, self.logger, self.device
        )


if __name__ == "__main__":
    server = FedSRServer()
    server.run()
