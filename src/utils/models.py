import json
import functools
from collections import OrderedDict
from typing import List, Optional
from copy import deepcopy

import torch
import torch.nn as nn
import torch.nn.functional as F
import torchvision.models as models
from torch import Tensor
import torch.distributions as distributions

from .tools import PROJECT_DIR


def get_model_arch(model_name):
    # static means the model arch is fixed.
    static = {
        "lenet5": LeNet5,
        "avgcnn": FedAvgCNN,
        "alex": AlexNet,
        "sqz": SqueezeNet,
        "2nn": TwoNN,
        "custom": CustomModel,
        "discriminator": Discriminator,
    }
    if model_name in static:
        return static[model_name]
    else:
        if "fedsr" in model_name:
            return functools.partial(
                Model_4_FedSR, base_model_name=model_name.split("_")[-1]
            )
        if "res" in model_name:
            return functools.partial(ResNet, version=model_name[3:])
        if "dense" in model_name:
            return functools.partial(DenseNet, version=model_name[5:])
        if "mobile" in model_name:
            return functools.partial(MobileNet, version=model_name[6:])
        if "efficient" in model_name:
            return functools.partial(EfficientNet, version=model_name[9:])
        if "squeeze" in model_name:
            return functools.partial(SqueezeNet, version=model_name[-1])
        raise ValueError(f"Unsupported model: {model_name}")


def get_domain_classes_num():
    try:
        with open(PROJECT_DIR / "data" / "domain" / "metadata.json", "r") as f:
            metadata = json.load(f)
        return metadata["class_num"]
    except:
        return 0


def get_synthetic_classes_num():
    try:
        with open(PROJECT_DIR / "data" / "synthetic" / "args.json", "r") as f:
            metadata = json.load(f)
        return metadata["class_num"]
    except:
        return 0


INPUT_CHANNELS = {
    "mnist": 1,
    "medmnistS": 1,
    "medmnistC": 1,
    "medmnistA": 1,
    "covid19": 3,
    "fmnist": 1,
    "emnist": 1,
    "femnist": 1,
    "cifar10": 3,
    "cinic10": 3,
    "svhn": 3,
    "cifar100": 3,
    "celeba": 3,
    "usps": 1,
    "tiny_imagenet": 3,
    "domain": 3,
}

NUM_CLASSES = {
    "mnist": 10,
    "medmnistS": 11,
    "medmnistC": 11,
    "medmnistA": 11,
    "fmnist": 10,
    "svhn": 10,
    "emnist": 62,
    "femnist": 62,
    "cifar10": 10,
    "cinic10": 10,
    "cifar100": 100,
    "covid19": 4,
    "usps": 10,
    "celeba": 2,
    "tiny_imagenet": 200,
    "synthetic": get_synthetic_classes_num(),
    "domain": get_domain_classes_num(),
}


class DecoupledModel(nn.Module):
    def __init__(self):
        super(DecoupledModel, self).__init__()
        self.need_all_features_flag = False
        self.all_features = []
        self.base: nn.Module = None
        self.classifier: nn.Module = None
        self.dropout: List[nn.Module] = []

    def need_all_features(self):
        target_modules = [
            module
            for module in self.base.modules()
            if isinstance(module, nn.Conv2d) or isinstance(module, nn.Linear)
        ]

        def get_feature_hook_fn(model, input, output):
            if self.need_all_features_flag:
                self.all_features.append(output.clone().detach())

        for module in target_modules:
            module.register_forward_hook(get_feature_hook_fn)

    def check_avaliability(self):
        if self.base is None or self.classifier is None:
            raise RuntimeError(
                "You need to re-write the base and classifier in your custom model class."
            )
        self.dropout = [
            module
            for module in list(self.base.modules()) + list(self.classifier.modules())
            if isinstance(module, nn.Dropout)
        ]

    def forward(self, x: Tensor) -> Tensor:
        return self.classifier(self.base(x))

    def get_final_features(self, x: Tensor, detach=True) -> Tensor:
        if len(self.dropout) > 0:
            for dropout in self.dropout:
                dropout.eval()

        func = (lambda x: x.clone().detach()) if detach else (lambda x: x)
        out = self.base(x)

        if len(self.dropout) > 0:
            for dropout in self.dropout:
                dropout.train()

        return func(out)

    def get_all_features(self, x: Tensor) -> Optional[List[Tensor]]:
        feature_list = None
        if len(self.dropout) > 0:
            for dropout in self.dropout:
                dropout.eval()

        self.need_all_features_flag = True
        _ = self.base(x)
        self.need_all_features_flag = False

        if len(self.all_features) > 0:
            feature_list = self.all_features
            self.all_features = []

        if len(self.dropout) > 0:
            for dropout in self.dropout:
                dropout.train()

        return feature_list


# CNN used in FedAvg
class FedAvgCNN(DecoupledModel):
    def __init__(self, dataset: str):
        super(FedAvgCNN, self).__init__()
        features_length = {
            "mnist": 1024,
            "medmnistS": 1024,
            "medmnistC": 1024,
            "medmnistA": 1024,
            "covid19": 196736,
            "fmnist": 1024,
            "emnist": 1024,
            "femnist": 1,
            "cifar10": 1600,
            "cinic10": 1600,
            "cifar100": 1600,
            "tiny_imagenet": 3200,
            "celeba": 133824,
            "svhn": 1600,
            "usps": 800,
        }
        self.base = nn.Sequential(
            OrderedDict(
                conv1=nn.Conv2d(INPUT_CHANNELS[dataset], 32, 5),
                activation1=nn.ReLU(),
                pool1=nn.MaxPool2d(2),
                conv2=nn.Conv2d(32, 64, 5),
                activation2=nn.ReLU(),
                pool2=nn.MaxPool2d(2),
                flatten=nn.Flatten(),
                fc1=nn.Linear(features_length[dataset], 512),
            )
        )
        self.classifier = nn.Linear(512, NUM_CLASSES[dataset])

    def forward(self, x):
        return self.classifier(F.relu(self.base(x)))


class LeNet5(DecoupledModel):
    def __init__(self, dataset: str) -> None:
        super(LeNet5, self).__init__()
        feature_length = {
            "mnist": 256,
            "medmnistS": 256,
            "medmnistC": 256,
            "medmnistA": 256,
            "covid19": 49184,
            "fmnist": 256,
            "emnist": 256,
            "femnist": 256,
            "cifar10": 400,
            "cinic10": 400,
            "svhn": 400,
            "cifar100": 400,
            "celeba": 33456,
            "usps": 200,
            "tiny_imagenet": 2704,
        }
        self.base = nn.Sequential(
            OrderedDict(
                conv1=nn.Conv2d(INPUT_CHANNELS[dataset], 6, 5),
                bn1=nn.BatchNorm2d(6),
                activation1=nn.ReLU(),
                pool1=nn.MaxPool2d(2),
                conv2=nn.Conv2d(6, 16, 5),
                bn2=nn.BatchNorm2d(16),
                activation2=nn.ReLU(),
                pool2=nn.MaxPool2d(2),
                flatten=nn.Flatten(),
                fc1=nn.Linear(feature_length[dataset], 120),
                activation3=nn.ReLU(),
                fc2=nn.Linear(120, 84),
            )
        )

        self.classifier = nn.Linear(84, NUM_CLASSES[dataset])

    def forward(self, x):
        return self.classifier(F.relu(self.base(x)))


class TwoNN(DecoupledModel):
    def __init__(self, dataset):
        super(TwoNN, self).__init__()

        def get_synthetic_dimension():
            try:
                with open(PROJECT_DIR / "data" / "synthetic" / "args.json", "r") as f:
                    metadata = json.load(f)
                return metadata["dimension"]
            except:
                return 0

        features_length = {
            "mnist": 784,
            "medmnistS": 784,
            "medmnistC": 784,
            "medmnistA": 784,
            "fmnist": 784,
            "emnist": 784,
            "femnist": 784,
            "cifar10": 3072,
            "cinic10": 3072,
            "svhn": 3072,
            "cifar100": 3072,
            "usps": 1536,
            "synthetic": get_synthetic_dimension(),
        }
        self.base = nn.Sequential(
            nn.Linear(features_length[dataset], 200),
            nn.ReLU(inplace=True),
            nn.Linear(200, 200),
            nn.ReLU(inplace=True),
        )
        # self.base = nn.Linear(features_length[dataset], 200)
        self.classifier = nn.Linear(200, NUM_CLASSES[dataset])
        self.activation = nn.ReLU()

    def need_all_features(self):
        return

    def forward(self, x):
        x = torch.flatten(x, start_dim=1)
        x = self.classifier(self.base(x))
        return x

    def get_final_features(self, x, detach=True):
        func = (lambda x: x.clone().detach()) if detach else (lambda x: x)
        x = torch.flatten(x, start_dim=1)
        x = self.base(x)
        return func(x)

    def get_all_features(self, x):
        raise RuntimeError("2NN has 0 Conv layer, so is unable to get all features.")


class AlexNet(DecoupledModel):
    def __init__(self, dataset):
        super().__init__()

        # NOTE: If you don't want parameters pretrained, set `pretrained` as False
        pretrained = True
        alexnet = models.alexnet(
            weights=models.AlexNet_Weights.DEFAULT if pretrained else None
        )
        self.base = alexnet
        self.classifier = nn.Linear(
            alexnet.classifier[-1].in_features, NUM_CLASSES[dataset]
        )
        self.base.classifier[-1] = nn.Identity()


class SqueezeNet(DecoupledModel):
    def __init__(self, version, dataset):
        super().__init__()

        # NOTE: If you don't want parameters pretrained, set `pretrained` as False
        pretrained = True
        archs = {
            "0": (models.squeezenet1_0, models.SqueezeNet1_0_Weights.DEFAULT),
            "1": (models.squeezenet1_1, models.SqueezeNet1_1_Weights.DEFAULT),
        }
        squeezenet: models.SqueezeNet = archs[version][0](
            weights=archs[version][1] if pretrained else None
        )
        self.base = squeezenet.features
        self.classifier = nn.Sequential(
            nn.Dropout(),
            nn.Conv2d(
                squeezenet.classifier[1].in_channels,
                NUM_CLASSES[dataset],
                kernel_size=1,
            ),
            nn.ReLU(True),
            nn.AdaptiveAvgPool2d((1, 1)),
            nn.Flatten(),
        )


class DenseNet(DecoupledModel):
    def __init__(self, version, dataset):
        super().__init__()
        archs = {
            "121": (models.densenet121, models.DenseNet121_Weights.DEFAULT),
            "161": (models.densenet161, models.DenseNet161_Weights.DEFAULT),
            "169": (models.densenet169, models.DenseNet169_Weights.DEFAULT),
            "201": (models.densenet201, models.DenseNet201_Weights.DEFAULT),
        }
        # NOTE: If you don't want parameters pretrained, set `pretrained` as False
        pretrained = True
        densenet: models.DenseNet = archs[version][0](
            weights=archs[version][1] if pretrained else None
        )
        self.base = densenet
        self.classifier = nn.Linear(
            densenet.classifier.in_features, NUM_CLASSES[dataset]
        )
        self.base.classifier = nn.Identity()


class ResNet(DecoupledModel):
    def __init__(self, version, dataset):
        super().__init__()
        archs = {
            "18": (models.resnet18, models.ResNet18_Weights.DEFAULT),
            "34": (models.resnet34, models.ResNet34_Weights.DEFAULT),
            "50": (models.resnet50, models.ResNet50_Weights.DEFAULT),
            "101": (models.resnet101, models.ResNet101_Weights.DEFAULT),
            "152": (models.resnet152, models.ResNet152_Weights.DEFAULT),
        }

        # NOTE: If you don't want parameters pretrained, set `pretrained` as False
        pretrained = True
        resnet: models.ResNet = archs[version][0](
            weights=archs[version][1] if pretrained else None
        )
        self.base = resnet
        self.classifier = nn.Linear(self.base.fc.in_features, NUM_CLASSES[dataset])
        self.base.fc = nn.Identity()


class MobileNet(DecoupledModel):
    def __init__(self, version, dataset):
        super().__init__()
        archs = {
            "2": (models.mobilenet_v2, models.MobileNet_V2_Weights.DEFAULT),
            "3s": (
                models.mobilenet_v3_small,
                models.MobileNet_V3_Small_Weights.DEFAULT,
            ),
            "3l": (
                models.mobilenet_v3_large,
                models.MobileNet_V3_Large_Weights.DEFAULT,
            ),
        }
        # NOTE: If you don't want parameters pretrained, set `pretrained` as False
        pretrained = True
        mobilenet = archs[version][0](weights=archs[version][1] if pretrained else None)
        self.base = mobilenet
        self.classifier = nn.Linear(
            mobilenet.classifier[-1].in_features, NUM_CLASSES[dataset]
        )
        self.base.classifier[-1] = nn.Identity()


class EfficientNet(DecoupledModel):
    def __init__(self, version, dataset):
        super().__init__()
        archs = {
            "0": (models.efficientnet_b0, models.EfficientNet_B0_Weights.DEFAULT),
            "1": (models.efficientnet_b1, models.EfficientNet_B1_Weights.DEFAULT),
            "2": (models.efficientnet_b2, models.EfficientNet_B2_Weights.DEFAULT),
            "3": (models.efficientnet_b3, models.EfficientNet_B3_Weights.DEFAULT),
            "4": (models.efficientnet_b4, models.EfficientNet_B4_Weights.DEFAULT),
            "5": (models.efficientnet_b5, models.EfficientNet_B5_Weights.DEFAULT),
            "6": (models.efficientnet_b6, models.EfficientNet_B6_Weights.DEFAULT),
            "7": (models.efficientnet_b7, models.EfficientNet_B7_Weights.DEFAULT),
        }
        # NOTE: If you don't want parameters pretrained, set `pretrained` as False
        pretrained = True
        efficientnet: models.EfficientNet = archs[version][0](
            weights=archs[version][1] if pretrained else None
        )
        self.base = efficientnet
        self.classifier = nn.Linear(
            efficientnet.classifier[-1].in_features, NUM_CLASSES[dataset]
        )
        self.base.classifier[-1] = nn.Identity()


class Discriminator(nn.Module):
    # discriminator for adversarial training in ADCOL
    def __init__(self, base_model, client_num):
        super(Discriminator, self).__init__()
        try:
            in_features = base_model.classifier.in_features
        except:
            raise ValueError("base model has no classifier")
        self.discriminator = nn.Sequential(
            nn.Linear(in_features, 512, bias=False),
            nn.BatchNorm1d(512),
            nn.ReLU(),
            nn.Linear(512, 512, bias=False),
            nn.BatchNorm1d(512),
            nn.ReLU(),
            nn.Linear(512, client_num, bias=False),
        )

    def forward(self, x):
        x = self.discriminator(x)
        return x


class Model_4_FedSR(DecoupledModel):
    # modify base model to suit FedSR
    def __init__(self, base_model_name, dataset) -> None:
        super().__init__()
        self.base_model = get_model_arch(base_model_name)(dataset=dataset)
        self.z_dim = self.base_model.classifier.in_features
        out_dim = 2 * self.z_dim
        self.base = deepcopy(self.base_model.base)
        self.classifier = deepcopy(self.base_model.classifier)
        self.base.classifier[1] = nn.Linear(
            self.base_model.classifier.in_features, out_dim
        )
        self.classifier = nn.Linear(self.z_dim, NUM_CLASSES[dataset])
        self.r_mu = nn.Parameter(torch.zeros(NUM_CLASSES[dataset], self.z_dim))
        self.r_sigma = nn.Parameter(torch.ones(NUM_CLASSES[dataset], self.z_dim))
        self.C = nn.Parameter(torch.ones([]))

    def featurize(self, x, num_samples=1, return_dist=False):
        # designed for FedSR
        z_params = self.base(x)
        z_mu = z_params[:, : self.z_dim]
        z_sigma = F.softplus(z_params[:, self.z_dim :])
        z_dist = distributions.Independent(
            distributions.normal.Normal(z_mu, z_sigma), 1
        )
        z = z_dist.rsample([num_samples]).view([-1, self.z_dim])

        if return_dist:
            return z, (z_mu, z_sigma)
        else:
            return z

    def forward(self, x):
        z = self.featurize(x)
        logits = self.classifier(z)
        return logits


# NOTE: You can build your custom model here.
# What you only need to do is define the architecture in __init__().
# Don't need to consider anything else, which are handled by DecoupledModel well already.
# Run `python *.py -m custom` to use your custom model.
class CustomModel(DecoupledModel):
    def __init__(self, dataset):
        super().__init__()
        # You need to define:
        # 1. self.base (the feature extractor part)
        # 2. self.classifier (normally the final fully connected layer)
        # The default forwarding process is: out = self.classifier(self.base(input))
        pass
