import networkx as nx
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch_geometric.data import Data
from torch_geometric.nn import GCNConv
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_absolute_error, mean_squared_error

# Load the GML File
gml_file = "/Users/abhishekjoshi/Documents/GitHub/stock_forecasting_CAI/USP-2/stock_graph_with_edges.gml"
graph = nx.read_gml(gml_file)

# Convert the NetworkX graph to PyTorch Geometric Data
def nx_to_pyg_data(graph):
    node_features = []
    node_labels = []
    node_mapping = {}

    for i, (node, data) in enumerate(graph.nodes(data=True)):
        # Extract node features
        node_features.append([
            float(data.get('volume_weighted_sentiment', 0)),
            float(data.get('daily_return', 0)),
            float(data.get('rolling_avg', 0)),
            float(data.get('volatility', 0)),
            float(data.get('momentum', 0)),
        ])
        # Use daily return as the target label
        node_labels.append(float(data.get('daily_return', 0)))
        node_mapping[node] = i

    # Convert edges
    edge_index = []
    for src, dst in graph.edges():
        edge_index.append([node_mapping[src], node_mapping[dst]])

    edge_index = torch.tensor(edge_index, dtype=torch.long).t().contiguous()
    x = torch.tensor(node_features, dtype=torch.float)
    y = torch.tensor(node_labels, dtype=torch.float)

    return Data(x=x, edge_index=edge_index, y=y)

data = nx_to_pyg_data(graph)

# Preprocess features and labels
scaler = StandardScaler()
data.x = torch.tensor(scaler.fit_transform(data.x.numpy()), dtype=torch.float)
data.y = (data.y - data.y.mean()) / data.y.std()  # Standardize labels

# Split data into train, validation, and test sets
def split_data(data, train_ratio=0.7, val_ratio=0.15):
    indices = np.arange(data.num_nodes)
    train_idx, test_idx = train_test_split(
        indices, test_size=(1 - train_ratio), random_state=42
    )
    val_idx, test_idx = train_test_split(
        test_idx, test_size=(len(test_idx) - int(val_ratio * len(indices))) / len(test_idx), random_state=42
    )

    return torch.tensor(train_idx, dtype=torch.long), torch.tensor(val_idx, dtype=torch.long), torch.tensor(test_idx, dtype=torch.long)

data.train_idx, data.val_idx, data.test_idx = split_data(data)

# Define the enhanced GCN model
class EnhancedGCN(nn.Module):
    def __init__(self, in_channels, hidden_channels, out_channels):
        super(EnhancedGCN, self).__init__()
        self.conv1 = GCNConv(in_channels, hidden_channels)
        self.bn1 = nn.BatchNorm1d(hidden_channels)
        self.conv2 = GCNConv(hidden_channels, hidden_channels)
        self.bn2 = nn.BatchNorm1d(hidden_channels)
        self.conv3 = GCNConv(hidden_channels, out_channels)
        self.dropout = nn.Dropout(0.6)

    def forward(self, x, edge_index):
        x = self.conv1(x, edge_index)
        x = self.bn1(x)
        x = torch.relu(x)
        x = self.dropout(x)
        x = self.conv2(x, edge_index)
        x = self.bn2(x)
        x = torch.relu(x)
        x = self.dropout(x)
        x = self.conv3(x, edge_index)
        return x

# Train the GCN model
def train_model(model, data, epochs=100, lr=0.01):
    optimizer = optim.Adam(model.parameters(), lr=lr, weight_decay=5e-4)
    scheduler = optim.lr_scheduler.StepLR(optimizer, step_size=20, gamma=0.5)  # LR scheduler
    criterion = nn.MSELoss()

    for epoch in range(epochs):
        model.train()
        optimizer.zero_grad()
        output = model(data.x, data.edge_index).squeeze()
        loss = criterion(output[data.train_idx], data.y[data.train_idx])
        loss.backward()
        optimizer.step()
        scheduler.step()

        model.eval()
        with torch.no_grad():
            val_loss = criterion(output[data.val_idx], data.y[data.val_idx]).item()

        print(f"Epoch {epoch + 1}/{epochs}, Train Loss: {loss.item():.4f}, Val Loss: {val_loss:.4f}")

    return model

# Evaluate the model
def evaluate_model(model, data):
    model.eval()
    predictions = model(data.x, data.edge_index).squeeze().detach().numpy()
    true_values = data.y.detach().numpy()

    mae = mean_absolute_error(true_values[data.test_idx], predictions[data.test_idx])
    rmse = np.sqrt(mean_squared_error(true_values[data.test_idx], predictions[data.test_idx]))
    mape = np.mean(np.abs((true_values[data.test_idx] - predictions[data.test_idx]) / true_values[data.test_idx])) * 100

    directional_accuracy = np.mean(
        (np.sign(predictions[data.test_idx][1:] - predictions[data.test_idx][:-1]) ==
         np.sign(true_values[data.test_idx][1:] - true_values[data.test_idx][:-1]))
    )

    returns = predictions[data.test_idx] - true_values[data.test_idx]
    sharpe_ratio = np.mean(returns) / np.std(returns) if np.std(returns) != 0 else 0

    ic = np.corrcoef(predictions[data.test_idx], true_values[data.test_idx])[0, 1]

    hit_rate = np.mean(
        np.sign(predictions[data.test_idx]) == np.sign(true_values[data.test_idx])
    ) * 100

    metrics = {
        "MAE": mae,
        "RMSE": rmse,
        "MAPE (%)": mape,
        "Directional Accuracy (%)": directional_accuracy * 100,
        "Sharpe Ratio": sharpe_ratio,
        "Information Coefficient (IC)": ic,
        "Hit Rate (%)": hit_rate,
    }

    return metrics

# Main execution
in_channels = data.x.shape[1]
hidden_channels = 32  # Increased hidden dimensions
out_channels = 1

gcn_model = EnhancedGCN(in_channels, hidden_channels, out_channels)
trained_model = train_model(gcn_model, data, epochs=100, lr=0.01)
metrics = evaluate_model(trained_model, data)

print("Evaluation Metrics:")
for metric, value in metrics.items():
    print(f"{metric}: {value:.4f}")