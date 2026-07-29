"""RefineNet-UW: regressor subpixel de canto (estágio 2).

Entrada: patch 64×64 BGR centrado na estimativa grosseira do estágio 1.
Saída: (dx, dy) normalizado — posição do canto relativa ao centro do patch.
~420k parâmetros; inferência < 1 ms/patch em GPU, adequada a tempo real.
"""
import torch
import torch.nn as nn


class RefineNetUW(nn.Module):
    def __init__(self):
        super().__init__()
        def c(cin, cout, s=1):
            return nn.Sequential(
                nn.Conv2d(cin, cout, 3, stride=s, padding=1, bias=False),
                nn.BatchNorm2d(cout),
                nn.ReLU(inplace=True),
            )
        self.net = nn.Sequential(
            c(3, 32), c(32, 32),
            c(32, 64, s=2),   # 32
            c(64, 64),
            c(64, 128, s=2),  # 16
            c(128, 128),
            c(128, 128, s=2), # 8
            nn.AdaptiveAvgPool2d(1),
        )
        self.head = nn.Linear(128, 2)

    def forward(self, x):
        z = self.net(x).flatten(1)
        return torch.tanh(self.head(z))  # [-1,1] × MAX_OFF px
